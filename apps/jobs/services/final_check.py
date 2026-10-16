"""
The final check: what was ordered against what was made, at each line's
last step.

The coordinator sees the order, measures and counts what was made, and
changes only what differs. Octos compares. Everything matches: the step
is done, and when every piece of the job has passed, the job is ready and
the customer is told. Anything differs: the piece is never handed over.
It goes back to be made again from its print step, on its own machine if
that is up, and the steps after it are done again too. Nothing is stored
about how long that will take; the estimate is worked out on every look,
so it grows the moment the piece goes back.
"""

from django.db import transaction

from apps.jobs.models import FinalCheck, JobStep
from apps.jobs.services.steps import (
    StepRefused, fill, mark_done, pick_machine,
)

# Not shown as their own rows: the price was built from these, and size
# and quantity have rows of their own.
PRICED = {'quantity', 'sets', 'pages', 'unit_price', 'line_total'}
UNITS = ('in', 'ft', 'cm', 'mm', 'm')


def _pretty(key):
    for unit in UNITS:
        if key.endswith(f'_{unit}'):
            base = key[: -len(unit) - 1].replace('_', ' ')
            return f'{base[:1].upper()}{base[1:]} ({unit})'
    base = key.replace('_', ' ')
    return f'{base[:1].upper()}{base[1:]}'


def _size(line):
    """The piece's own width and height if it has them, else its paper size."""
    specs = line.specifications or {}
    for unit in UNITS:
        w, h = specs.get(f'width_{unit}'), specs.get(f'height_{unit}')
        if w not in (None, '') and h not in (None, ''):
            return f'{w} × {h} {unit}', {f'width_{unit}', f'height_{unit}'}
    return (line.paper_size or ''), set()


def ordered_rows(line):
    """What the customer ordered, row by row, in the words the floor uses."""
    size, used = _size(line)
    quantity = f'{line.quantity}'
    if (line.pages or 1) > 1:
        quantity += f' × {line.pages}pp'

    rows = [
        {'field': 'size', 'label': 'Size', 'ordered': size},
        {'field': 'quantity', 'label': 'Quantity', 'ordered': quantity},
    ]
    for key, value in (line.specifications or {}).items():
        if key in PRICED or key in used or value in (None, ''):
            continue
        rows.append({'field': key, 'label': _pretty(key), 'ordered': str(value)})
    rows.append({
        'field': 'sides', 'label': 'Sides',
        'ordered': 'Double-sided' if line.sides == 'DOUBLE' else 'Single-sided',
    })
    return rows


def _same(a, b):
    """Equal as the floor would read them: case, spaces and x for × aside."""
    def norm(v):
        return str(v).lower().replace('×', 'x').replace(' ', '').strip()
    return norm(a) == norm(b)


def _is_last(step):
    return not JobStep.objects.filter(
        line_item=step.line_item, sequence__gt=step.sequence,
    ).exists()


def _ready_if_all_done(job, actor):
    """Every piece checked and passed: the job is ready, and the customer is told."""
    from apps.jobs.models import Job
    from apps.jobs.status_engine import JobStatusEngine

    fresh = Job.objects.get(pk=job.pk)
    if JobStep.objects.filter(job=fresh).exclude(state=JobStep.State.DONE).exists():
        return

    path = {
        'IN_PRODUCTION': ['FINISHING', 'QUALITY_CHECK', 'DONE'],
        'FINISHING':     ['QUALITY_CHECK', 'DONE'],
        'QUALITY_CHECK': ['DONE'],
    }.get(fresh.work_state, [])

    engine = JobStatusEngine(fresh)
    for state in path:
        engine.move_work(state, actor, notes='Final check passed')


def _send_back(step, branch):
    """
    Back to be made again, from the line's print step on. Its own machine
    if that is up, otherwise another that fits; everything after it is
    done again too.
    """
    line_steps = list(
        JobStep.objects
        .select_for_update(of=('self',))
        .select_related('station', 'machine__machine_type')
        .filter(line_item=step.line_item)
        .order_by('sequence')
    )
    prints = [s for s in line_steps if s.station.code == 'PRINT']
    start = prints[-1].sequence if prints else step.sequence

    to_fill = set()
    bench = None
    for s in line_steps:
        if s.sequence < start:
            continue
        if s.machine_id:
            to_fill.add(s.machine_id)
        if s.by_hand:
            bench = s.station
        if s.machine_id and not s.machine.is_available:
            replacement = pick_machine(branch, s.machine.machine_type, step.line_item)
            s.machine = replacement
            if replacement is not None:
                to_fill.add(replacement.pk)
        s.state = JobStep.State.WAITING
        s.reached_at = None
        s.done_at = None
        s.done_by = None
        s.save(update_fields=['machine', 'state', 'reached_at', 'done_at', 'done_by', 'updated_at'])

    from apps.production.models import Machine
    for machine in Machine.objects.filter(pk__in=to_fill):
        fill(branch, machine=machine)
    if bench is not None:
        fill(branch, station=bench)


def check(step_id, branch, actor, made=None, note=''):
    """
    Compare what was made with what was ordered, for the piece at its last
    step. Rows not given are taken as made exactly as ordered.
    """
    made = made or {}

    with transaction.atomic():
        step = (
            JobStep.objects
            .select_for_update(of=('self',))
            .select_related('job', 'line_item', 'machine', 'station')
            .filter(pk=step_id, job__branch=branch)
            .first()
        )
        if step is None:
            raise StepRefused('That step is not at this branch.')
        if step.state == JobStep.State.DONE:
            raise StepRefused('That piece has already been checked.')
        if not _is_last(step):
            raise StepRefused('The final check is at the last step for this piece.')
        unassigned = step.machine_id is None and not step.by_hand
        if step.state != JobStep.State.ACTIVE and not unassigned:
            raise StepRefused('Only the piece being worked can be checked.')

        rows = []
        for row in ordered_rows(step.line_item):
            value = made.get(row['field'], row['ordered'])
            rows.append({**row, 'made': str(value), 'match': _same(row['ordered'], value)})

        passed = all(r['match'] for r in rows)
        record = FinalCheck.objects.create(
            job         = step.job,
            line_item   = step.line_item,
            step        = step,
            outcome     = FinalCheck.Outcome.PASSED if passed else FinalCheck.Outcome.SENT_BACK,
            rows        = rows,
            promised_at = step.job.estimated_ready_at,
            note        = note,
            checked_by  = actor,
        )

        if passed:
            mark_done(step.pk, branch, actor, checked=True)
            _ready_if_all_done(step.job, actor)
        else:
            _send_back(step, branch)

        return record