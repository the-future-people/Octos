"""
A job's journey across the floor, step by step.

When a job is cleared, each line's route (ServiceStation, in sequence)
becomes its steps. Each step is given a machine: the right type, up,
wide enough for the work, and with the least waiting on it. A route step
that names no machine type is done by hand, at the one shared bench
(cutting a banner, eyelets, packing), even where its station also has
machines for other work. Consecutive by-hand steps on a line are one
visit to the bench, so they become one step. A step whose machines all failed to fit waits
unassigned, for the coordinator to place, or to mark done another way.

A queue is a machine's line-up (or the bench's): the steps that are
their line's current step, not done. The one on the machine is ACTIVE
and stays at the front; the rest wait by slack, the least first: the
job's promise less the work still left on the line. On a machine with
no operator, the front goes on by itself when the machine is free, as
it always has. On a staffed machine it waits for the operator's Start,
and only the moment it reached the front is recorded until then.

Every line ends at the bench. Where a route ends on a machine, a step
at hand finishing is added, so an operator's Done never closes a line
and the final check happens at finishing.

A line's later steps are not in any queue yet. A banner is not waiting
at the laminator while it is still printing.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import (
    Case, DecimalField, Exists, ExpressionWrapper, F, IntegerField,
    OuterRef, Subquery, Sum, Value, When,
)
from django.db.models.functions import Coalesce, Extract
from django.utils import timezone

from apps.jobs.models import JobStep

# What one of each unit is in millimetres, to test a piece against a
# machine's maximum width.
MM_PER = {'in': 25.4, 'ft': 304.8, 'cm': 10.0, 'mm': 1.0, 'm': 1000.0}

# Jobs that will never be worked. Their steps take no place in any queue
# and add nothing to a machine's load.
GONE = ('CANCELLED', 'VOIDED')


# ── Sizes and machines ───────────────────────────────────────────

def narrow_side_mm(line):
    """
    The shorter side of the piece, in millimetres, or None where the line
    has no dimensions. A roll machine needs the shorter side to fit its
    width; the longer side runs along the roll.
    """
    specs = line.specifications or {}
    for unit, mm in MM_PER.items():
        try:
            w = float(specs.get(f'width_{unit}'))
            h = float(specs.get(f'height_{unit}'))
        except (TypeError, ValueError):
            continue
        return min(w, h) * mm
    return None


def machine_load(machine):
    """Minutes of work not yet done on this machine."""
    minutes = (
        JobStep.objects
        .filter(machine=machine)
        .exclude(state=JobStep.State.DONE)
        .exclude(job__status__in=GONE)
        .values_list('expected_minutes', flat=True)
    )
    return sum(float(m) for m in minutes)


def pick_machine(branch, machine_type, line):
    """
    The machine this step should go to: of the right type, up, wide
    enough, and with the least work waiting. None when nothing fits,
    which leaves the step for the coordinator to place.
    """
    from apps.production.models import Machine

    if machine_type is None:
        return None

    need = narrow_side_mm(line)
    fits = [
        m for m in Machine.objects.filter(
            branch=branch, machine_type=machine_type,
            is_active=True, is_available=True,
        ).order_by('pk')
        if need is None or not m.max_width_mm or m.max_width_mm >= need
    ]
    if not fits:
        return None
    return min(fits, key=lambda m: (machine_load(m), m.pk))


def expected_minutes(branch, route, line):
    """
    The work itself, as the prediction service counts it: setup plus
    minutes per unit, measured where Octos has the figures and seeded
    where not. Sheets at the press, pieces everywhere else.
    """
    from apps.production.services.prediction_service import PredictionService

    quantity = line.quantity or 1
    units = quantity * (line.pages or 1) if route.station.code == 'PRINT' else quantity

    observed = PredictionService(branch)._observed_per_unit(route.station)
    per_unit = observed if observed is not None else float(route.minutes_per_unit)

    return Decimal(str(round(float(route.setup_minutes) + per_unit * units, 1)))


# ── Queues ───────────────────────────────────────────────────────

def is_staffed(machine):
    """A machine with at least one current operator. Its work starts only on their Start."""
    if machine is None:
        return False
    from apps.production.models import MachineOperator
    return MachineOperator.objects.filter(
        machine=machine, active_until__isnull=True, operator__is_active=True,
    ).exists()


def _current_only(qs):
    """Steps that are their line's current one: nothing earlier left undone."""
    earlier = (
        JobStep.objects
        .filter(line_item=OuterRef('line_item'), sequence__lt=OuterRef('sequence'))
        .exclude(state=JobStep.State.DONE)
    )
    return qs.annotate(blocked=Exists(earlier)).filter(blocked=False)


def queue(branch, machine=None, station=None):
    """
    A machine's line-up, or the bench's when machine is None: every step
    done by hand, whatever its station, since there is one bench. The step
    being worked first, then by promise. Unassigned steps are in neither;
    they wait for the coordinator.
    """
    from apps.jobs.models import JobHalt
    stopped = JobHalt.objects.filter(job=OuterRef('job'), resumed_at__isnull=True)
    qs = (
        JobStep.objects
        .filter(job__branch=branch)
        .exclude(state=JobStep.State.DONE)
        .exclude(job__status__in=GONE)
        # A halted job waits aside and keeps no place in the line-up until
        # it is resumed. One already on the machine stays, so a machine is
        # never given a second job while the first is stopped on it.
        .annotate(halted=Exists(stopped))
        .exclude(halted=True, state=JobStep.State.WAITING)
    )
    if machine is not None:
        qs = qs.filter(machine=machine)
    else:
        qs = qs.filter(machine__isnull=True, by_hand=True)

    # Minutes of work left on the line from this step on. Slack is the
    # promise less this, less now; now is the same for every job, so
    # ordering by (promise - work left) is ordering by slack.
    left = (
        JobStep.objects
        .filter(line_item=OuterRef('line_item'), sequence__gte=OuterRef('sequence'))
        .exclude(state=JobStep.State.DONE)
        .values('line_item')
        .annotate(total=Sum('expected_minutes'))
        .values('total')
    )
    return (
        _current_only(qs)
        .select_related('job', 'line_item', 'station', 'machine')
        .annotate(
            on_machine=Case(
                When(state=JobStep.State.ACTIVE, then=Value(0)),
                default=Value(1), output_field=IntegerField(),
            ),
            minutes_left=Coalesce(
                Subquery(left, output_field=DecimalField(max_digits=10, decimal_places=1)),
                Value(Decimal('0')),
                output_field=DecimalField(max_digits=10, decimal_places=1),
            ),
        )
        .annotate(start_by=ExpressionWrapper(
            Extract('job__estimated_ready_at', 'epoch') - F('minutes_left') * Value(60),
            output_field=DecimalField(max_digits=16, decimal_places=1),
        ))
        .order_by(
            'on_machine',
            F('start_by').asc(nulls_last=True),
            'job__created_at', 'pk',
        )
    )


def fill(branch, machine=None, station=None):
    """
    Put the front of a queue on the machine (or bench) if nothing is on it.
    Unassigned steps are in no queue, so they never start by themselves.
    """
    if machine is None and station is None:
        return None

    with transaction.atomic():
        line_up = list(queue(branch, machine=machine, station=station).select_for_update(of=('self',)))
        if not line_up or line_up[0].state == JobStep.State.ACTIVE:
            return None
        head = line_up[0]
        # On a staffed machine the front waits for the operator's Start;
        # only the moment it came to the front is recorded.
        if is_staffed(machine):
            if head.reached_at is None:
                head.reached_at = timezone.now()
                head.save(update_fields=['reached_at', 'updated_at'])
            return None
        head.state = JobStep.State.ACTIVE
        head.reached_at = timezone.now()
        head.save(update_fields=['state', 'reached_at', 'updated_at'])
        return head


# ── Making the steps ─────────────────────────────────────────────

def build_steps(job):
    """
    Turn each line's route into its steps and start whatever can start.

    Safe to call twice: a line that already has steps is left alone. A
    line whose service has no route gets no steps, and the job is moved
    by hand as before. A line's add-ons join its route rather than
    getting steps of their own.
    """
    from apps.production.models import ServiceStation, Station

    # Every line ends at the bench, so an operator's Done never closes a
    # line and the final check happens at finishing.
    finish = Station.objects.filter(code=Station.Code.FINISH, is_active=True).first()
    made = []
    # Add-on lines (lamination on a print) have no steps of their own:
    # their routes join their parent's, so the piece is printed, then
    # laminated, then bound, then packed, as one piece on the floor.
    for line in job.line_items.select_related('service').filter(parent__isnull=True):
        if line.steps.exists():
            continue

        parts = [
            (route, line) for route in
            ServiceStation.objects.filter(service=line.service).select_related('station', 'machine_type')
        ]
        for addon in line.addons.select_related('service'):
            parts += [
                (route, addon) for route in
                ServiceStation.objects.filter(service=addon.service).select_related('station', 'machine_type')
            ]
        # Stations run in their own order: print, cut, laminate, bind, finish.
        parts.sort(key=lambda p: (p[0].station.sequence, p[0].sequence))

        i, position = 0, 0
        while i < len(parts):
            route, _ = parts[i]
            by_hand = route.machine_type is None
            # Consecutive hand work is one visit to the bench, and two
            # routes at the same station are one step there.
            group = [parts[i]]
            while i + len(group) < len(parts):
                nxt, _ = parts[i + len(group)]
                if (by_hand and nxt.machine_type is None) or nxt.station_id == route.station_id:
                    group.append(parts[i + len(group)])
                else:
                    break
            position += 1
            made.append(JobStep.objects.create(
                job              = job,
                line_item        = line,
                station          = route.station,
                by_hand          = by_hand,
                machine          = None if by_hand else pick_machine(job.branch, route.machine_type, line),
                sequence         = position,
                expected_minutes = sum(
                    (expected_minutes(job.branch, r, source) for r, source in group), Decimal('0'),
                ),
            ))
            i += len(group)

        mine = [s for s in made if s.line_item_id == line.pk]
        if (finish is not None and mine and not mine[-1].by_hand
                and not any(s.station_id == finish.pk for s in mine)):
            position += 1
            made.append(JobStep.objects.create(
                job              = job,
                line_item        = line,
                station          = finish,
                by_hand          = True,
                machine          = None,
                sequence         = position,
                expected_minutes = Decimal('0'),
            ))

    machines = {s.machine_id: s.machine for s in made if s.machine_id}
    for machine in machines.values():
        fill(job.branch, machine=machine)
    by_hand = next((s for s in made if s.by_hand), None)
    if by_hand is not None:
        fill(job.branch, station=by_hand.station)

    return made


# ── Moving on ────────────────────────────────────────────────────

class StepRefused(Exception):
    """The step cannot be moved on, and the message says why."""


def start_step(step_id, branch, actor):
    """
    The operator's Start on a staffed machine: when the work really began.
    Only the front of the queue, only by someone assigned to the machine,
    and only when nothing else is on it. The machine's row is locked first
    so two Starts on one machine cannot both succeed.
    """
    from apps.jobs.models import Job
    from apps.production.models import Machine

    with transaction.atomic():
        step = (
            JobStep.objects
            .select_related('job')
            .filter(pk=step_id, job__branch=branch)
            .first()
        )
        if step is None:
            raise StepRefused('That step is not at this branch.')
        if step.machine_id is None:
            raise StepRefused('Only work on a machine is started here.')

        machine = Machine.objects.select_for_update().get(pk=step.machine_id)
        step = JobStep.objects.select_for_update(of=('self',)).select_related('job').get(pk=step.pk)

        if not is_staffed(machine):
            raise StepRefused(f'{machine.name} has no operator. Its work starts by itself.')
        if not machine.operator_assignments.filter(operator=actor, active_until__isnull=True).exists():
            raise StepRefused(f'You are not assigned to {machine.name}.')
        if not machine.is_usable:
            raise StepRefused(f'{machine.name} is down.')
        if step.state == JobStep.State.ACTIVE:
            raise StepRefused('That job has already started.')
        if step.state == JobStep.State.DONE:
            raise StepRefused('That job is already done.')
        if any(h.resumed_at is None for h in step.job.halts.all()):
            raise StepRefused(f'{step.job.job_number} is halted. Resume it first.')

        line_up = list(queue(branch, machine=machine))
        if line_up and line_up[0].state == JobStep.State.ACTIVE:
            raise StepRefused(
                f'{line_up[0].job.job_number} is still on {machine.name}. Mark it done first.'
            )
        if not line_up or line_up[0].pk != step.pk:
            raise StepRefused('Only the job at the front of the queue can start.')

        now = timezone.now()
        step.state      = JobStep.State.ACTIVE
        step.started_at = now
        step.started_by = actor
        step.reached_at = step.reached_at or now
        step.save(update_fields=['state', 'started_at', 'started_by', 'reached_at', 'updated_at'])
        Job.objects.filter(pk=step.job_id, work_started_at__isnull=True).update(work_started_at=now)
        return step


# What the operator can report, and the halt reason each becomes.
PROBLEMS = {
    'MACHINE_DOWN': 'MACHINE_BREAKDOWN',
    'FILE_FAULT':   'FILE_FAULT',
    'MATERIAL_OUT': 'MATERIALS_OUT',
}


def report_problem(step_id, branch, actor, kind, note=''):
    """
    The operator's Problem, on the job running on their machine.

    Machine down takes the machine out: the running job halts, and what
    was queued moves to another machine that fits or waits for this one.
    A file fault or material out stops this job only: it comes off the
    machine and is halted for the coordinator, and the next job comes
    forward. (Setting aside every job that needs a missing material waits
    until Octos knows what each job uses.)
    """
    from apps.jobs.status_engine import JobStatusEngine
    from apps.production.services.machine_service import MachineService

    reason = PROBLEMS.get(kind)
    if reason is None:
        raise StepRefused('Choose what happened: machine down, file fault or material out.')

    with transaction.atomic():
        step = (
            JobStep.objects
            .select_for_update(of=('self',))
            .select_related('job', 'machine')
            .filter(pk=step_id, job__branch=branch)
            .first()
        )
        if step is None:
            raise StepRefused('That step is not at this branch.')
        if step.machine_id is None or not step.machine.operator_assignments.filter(
                operator=actor, active_until__isnull=True).exists():
            raise StepRefused('That job is not on your machine.')
        if step.state != JobStep.State.ACTIVE:
            raise StepRefused('Report a problem on the job that is running.')

        if kind == 'MACHINE_DOWN':
            try:
                result = MachineService.mark_down(
                    step.machine, note or 'Machine breakdown', actor, note,
                )
            except (PermissionError, ValueError) as e:
                raise StepRefused(str(e))
            return {'kind': kind, **result}

        # This job comes off; the machine carries on.
        step.state      = JobStep.State.WAITING
        step.started_at = None
        step.started_by = None
        step.reached_at = None
        step.save(update_fields=['state', 'started_at', 'started_by', 'reached_at', 'updated_at'])
        try:
            JobStatusEngine(step.job).halt(reason=reason, actor=actor, note=note)
        except (PermissionError, ValueError) as e:
            raise StepRefused(str(e))

        fill(branch, machine=step.machine)
        return {'kind': kind, 'job_number': step.job.job_number, 'machine': step.machine.name}


def sync_stage(job, actor):
    """
    Keep the customer's stage in step with the floor. When every line has
    finished printing, the job is in Finishing. Finishing to ready stays
    the coordinator's quality check, so nothing here moves it further.

    A job with no print steps at all goes to Finishing as soon as it is
    cleared: there is nothing to print.
    """
    from apps.jobs.models import Job
    from apps.jobs.status_engine import JobStatusEngine

    fresh = Job.objects.get(pk=job.pk)
    steps = JobStep.objects.filter(job=fresh)
    if not steps.exists() or fresh.work_state != 'IN_PRODUCTION':
        return

    printing_left = (
        steps.filter(station__code='PRINT')
        .exclude(state=JobStep.State.DONE)
        .exists()
    )
    if not printing_left:
        JobStatusEngine(fresh).move_work(
            'FINISHING', actor, notes='Every line has finished printing',
        )


def mark_done(step_id, branch, actor, checked=False, made=None, spoilt=None):
    """
    The job on a machine (or bench) is finished there. The next job on
    that machine moves up, this line moves to its next step, and the
    customer's stage follows.

    A line's last step is finished only through the final check (checked
    is set by it), so no piece reaches a customer unexamined.

    Only the job actually being worked can be marked done, with one
    exception: unassigned work, whose machine the branch does not have or
    which nothing could take, may be marked done by the coordinator when
    it was done another way. It must still be the line's current step.
    """
    with transaction.atomic():
        step = (
            JobStep.objects
            # Lock the step's own row only. Its machine may be empty (the
            # bench, or unassigned), and PostgreSQL cannot lock the empty
            # side of a join.
            .select_for_update(of=('self',))
            .select_related('job', 'machine', 'station')
            .filter(pk=step_id, job__branch=branch)
            .first()
        )
        if step is None:
            raise StepRefused('That step is not at this branch.')
        unassigned = step.machine_id is None and not step.by_hand
        if unassigned:
            earlier_left = (
                JobStep.objects
                .filter(line_item=step.line_item, sequence__lt=step.sequence)
                .exclude(state=JobStep.State.DONE)
                .exists()
            )
            if earlier_left:
                raise StepRefused('Finish the steps before this one first.')
        elif step.state != JobStep.State.ACTIVE:
            raise StepRefused(
                'Only the job on the machine can be marked done.'
            )
        is_last = not JobStep.objects.filter(
            line_item=step.line_item, sequence__gt=step.sequence,
        ).exists()
        if is_last and not checked:
            raise StepRefused(
                'This is the last step for this piece. Use the final check.'
            )
        if any(h.resumed_at is None for h in step.job.halts.all()):
            raise StepRefused(
                f'{step.job.job_number} is halted. Resume it first.'
            )

        step.state   = JobStep.State.DONE
        step.done_at = timezone.now()
        step.done_by = actor
        fields = ['state', 'done_at', 'done_by', 'updated_at']
        if made is not None:
            step.quantity_made = made
            fields.append('quantity_made')
        if spoilt is not None:
            step.quantity_spoilt = spoilt
            fields.append('quantity_spoilt')
        step.save(update_fields=fields)

        # The next job on this machine (or bench) moves up.
        if step.machine_id or step.by_hand:
            fill(branch, machine=step.machine, station=step.station)

        # This line's next step joins its own queue, and starts if that
        # machine is free.
        following = (
            JobStep.objects
            .filter(line_item=step.line_item, sequence__gt=step.sequence)
            .exclude(state=JobStep.State.DONE)
            .select_related('machine', 'station')
            .order_by('sequence')
            .first()
        )
        if following is not None and (following.machine_id or following.by_hand):
            fill(branch, machine=following.machine, station=following.station)

        sync_stage(step.job, actor)
        return step


def move_step(step_id, branch, machine_id, actor):
    """
    Put a step on another machine. Waiting and unassigned steps can move
    freely; the step on a machine only when that machine is down, since
    otherwise it is physically being worked. The target must do this
    station's work, be up, and be wide enough for the piece.
    """
    from apps.production.models import Machine

    with transaction.atomic():
        step = (
            JobStep.objects
            .select_for_update(of=('self',))
            .select_related('machine', 'station', 'line_item')
            .filter(pk=step_id, job__branch=branch)
            .first()
        )
        if step is None:
            raise StepRefused('That step is not at this branch.')
        if step.state == JobStep.State.DONE:
            raise StepRefused('That step is already done.')
        if step.by_hand:
            raise StepRefused('That work is done by hand, at the bench.')
        if (step.state == JobStep.State.ACTIVE
                and step.machine_id and step.machine.is_available):
            raise StepRefused(
                'That job is on the machine now. Mark it done or halt it first.'
            )

        target = (
            Machine.objects
            .select_related('machine_type')
            .filter(pk=machine_id, branch=branch, is_active=True)
            .first()
        )
        if target is None:
            raise StepRefused('That machine is not at this branch.')
        if target.machine_type.station_id != step.station_id:
            raise StepRefused(f'{target.name} does not do this work.')
        if not target.is_available:
            raise StepRefused(f'{target.name} is down.')
        need = narrow_side_mm(step.line_item)
        if need and target.max_width_mm and target.max_width_mm < need:
            raise StepRefused(f'This piece is too wide for {target.name}.')

        was = step.machine
        step.machine = target
        if step.state == JobStep.State.ACTIVE:
            step.state = JobStep.State.WAITING
            step.reached_at = None
        step.save(update_fields=['machine', 'state', 'reached_at', 'updated_at'])

        if was is not None:
            fill(branch, machine=was)
        fill(branch, machine=target)
        return step