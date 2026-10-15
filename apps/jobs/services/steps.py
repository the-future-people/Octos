"""
A job's journey across the floor, step by step.

When a job is cleared, each line's route (ServiceStation, in sequence)
becomes its steps. Each step is given a machine: the right type, up,
wide enough for the work, and with the least waiting on it. A station
with no machines at all is hand finishing, at the shared bench. A step
whose machines all failed to fit waits unassigned, for the coordinator
to place by hand.

A queue is a machine's line-up (or the bench's): the steps that are
their line's current step, not done. The one on the machine is ACTIVE
and stays at the front; the rest wait by the job's promise, soonest
first. There is no Start button. A step becomes ACTIVE when it reaches
the front, and that moment is recorded.

A line's later steps are not in any queue yet. A banner is not waiting
at the laminator while it is still printing.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Case, Exists, F, IntegerField, OuterRef, Value, When
from django.utils import timezone

from apps.jobs.models import JobStep

# What one of each unit is in millimetres, to test a piece against a
# machine's maximum width.
MM_PER = {'in': 25.4, 'ft': 304.8, 'cm': 10.0, 'mm': 1.0, 'm': 1000.0}


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


def is_bench(station):
    """A station no machine belongs to is worked by hand."""
    from apps.production.models import MachineType
    return not MachineType.objects.filter(station=station, is_active=True).exists()


def machine_load(machine):
    """Minutes of work not yet done on this machine."""
    minutes = (
        JobStep.objects
        .filter(machine=machine)
        .exclude(state=JobStep.State.DONE)
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
    A machine's line-up, or the bench's when machine is None and station
    is a bench station. The step on the machine first, then by promise.
    """
    qs = JobStep.objects.filter(job__branch=branch).exclude(state=JobStep.State.DONE)
    if machine is not None:
        qs = qs.filter(machine=machine)
    else:
        qs = qs.filter(machine__isnull=True, station=station)

    return (
        _current_only(qs)
        .select_related('job', 'line_item', 'station', 'machine')
        .annotate(on_machine=Case(
            When(state=JobStep.State.ACTIVE, then=Value(0)),
            default=Value(1), output_field=IntegerField(),
        ))
        .order_by(
            'on_machine',
            F('job__estimated_ready_at').asc(nulls_last=True),
            'job__created_at', 'pk',
        )
    )


def fill(branch, machine=None, station=None):
    """
    Put the front of a queue on the machine if nothing is on it. Unassigned
    steps (a machine type exists, no machine was given) never start by
    themselves: they wait for the coordinator.
    """
    if machine is None and (station is None or not is_bench(station)):
        return None

    with transaction.atomic():
        line_up = list(queue(branch, machine=machine, station=station).select_for_update(of=('self',)))
        if not line_up or line_up[0].state == JobStep.State.ACTIVE:
            return None
        head = line_up[0]
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
    by hand as before.
    """
    from apps.production.models import ServiceStation

    made = []
    for line in job.line_items.select_related('service'):
        if line.steps.exists():
            continue
        routes = (
            ServiceStation.objects
            .filter(service=line.service)
            .select_related('station', 'machine_type')
            .order_by('sequence')
        )
        for route in routes:
            made.append(JobStep.objects.create(
                job              = job,
                line_item        = line,
                station          = route.station,
                machine          = pick_machine(job.branch, route.machine_type, line),
                sequence         = route.sequence,
                expected_minutes = expected_minutes(job.branch, route, line),
            ))

    for machine_id, station in {(s.machine_id, s.station) for s in made}:
        if machine_id:
            fill(job.branch, machine=made_machine(made, machine_id))
        else:
            fill(job.branch, station=station)

    return made


def made_machine(steps, machine_id):
    return next(s.machine for s in steps if s.machine_id == machine_id)


# ── Moving on ────────────────────────────────────────────────────

class StepRefused(Exception):
    """The step cannot be moved on, and the message says why."""


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


def mark_done(step_id, branch, actor):
    """
    The job on a machine is finished there. The next job on that machine
    moves up, this line moves to its next step, and the customer's stage
    follows. Only the job actually on the machine can be marked done: a
    waiting one has not been worked, and an unassigned one has nowhere it
    was worked.
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
        if step.state != JobStep.State.ACTIVE:
            raise StepRefused(
                'Only the job on the machine can be marked done.'
            )
        if any(h.resumed_at is None for h in step.job.halts.all()):
            raise StepRefused(
                f'{step.job.job_number} is halted. Resume it first.'
            )

        step.state   = JobStep.State.DONE
        step.done_at = timezone.now()
        step.done_by = actor
        step.save(update_fields=['state', 'done_at', 'done_by', 'updated_at'])

        # The next job on this machine (or bench) moves up.
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
        if following is not None:
            fill(branch, machine=following.machine, station=following.station)

        sync_stage(step.job, actor)
        return step