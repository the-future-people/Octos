"""
How long until a job's stage is done, worked out from the floor as it is
right now.

Each queue is walked from the front: the job being worked has what is
left of its own work, and every job behind it adds its own. A line's later
steps add their work after that. The customer's stage is done when its
last line is: In press when every line has printed, Finishing when every
line has finished everything.

Computed on every read, never stored, so a job running long, a machine
going down or a queue growing shows up the next time anyone looks.

Two honesty rules. A step past its expected time never counts down to
nothing: it keeps a small remainder and is flagged as running over. And
the numbers are rounded up — to five minutes under an hour, fifteen above
— because "about 15 minutes" that becomes 20 costs more trust than
"about 20" that becomes 15.
"""

import math
from dataclasses import dataclass

from django.utils import timezone

from apps.jobs.models import JobStep

# What a step past its expected time is still given. Never nothing while
# the work is visibly not done.
OVERRUN_REMAINDER = 5.0


@dataclass
class StageEstimate:
    stage: str               # 'press' | 'finishing'
    minutes_left: int        # rounded up, never 0 while work remains
    ready_at: object         # aware datetime, walked through opening hours
    running_over: bool       # something being worked is past its time
    held_up: bool            # waiting on a machine that is down, or unplaced

    def as_dict(self):
        return {
            'stage':        self.stage,
            'minutes_left': self.minutes_left,
            'ready_at':     self.ready_at.isoformat() if self.ready_at else None,
            'running_over': self.running_over,
            'held_up':      self.held_up,
        }


def round_up(minutes):
    """Up to 5 minutes under an hour, up to 15 above; never below 5."""
    if minutes <= 0:
        return 5
    step = 5 if minutes < 60 else 15
    return max(5, int(math.ceil(minutes / step) * step))


def _left_on_machine(step, now):
    """
    Minutes of work this step still needs, and whether it is running over.
    Waiting steps need all of theirs.
    """
    expected = float(step.expected_minutes)
    if step.state != JobStep.State.ACTIVE or step.reached_at is None:
        return expected, False
    elapsed = (now - step.reached_at).total_seconds() / 60
    if elapsed >= expected:
        return OVERRUN_REMAINDER, True
    return expected - elapsed, False


def _finish_of_current(step, now):
    """
    Minutes until this line's current step is done: everything ahead of it
    in its queue, then itself. An unassigned step is in no queue, so only
    its own work can be counted, and it is held up.
    """
    from apps.jobs.services.steps import queue

    branch = step.job.branch
    if step.machine_id is None and not step.by_hand:
        own, over = _left_on_machine(step, now)
        return own, over, True

    held_up = bool(step.machine_id and not step.machine.is_available)
    line_up = (
        queue(branch, machine=step.machine)
        if step.machine_id else queue(branch, station=step.station)
    )

    total = 0.0
    over = False
    for ahead in line_up:
        left, running_over = _left_on_machine(ahead, now)
        total += left
        if running_over:
            over = True
        if ahead.pk == step.pk:
            break
    return total, over, held_up


def estimate(job, now=None):
    """
    The customer's current stage and how long until it is done, or None
    where there is nothing to estimate: no steps, not in press or
    finishing, or every step already done and the job waiting only for
    its final check.
    """
    from apps.production.services.prediction_service import PredictionService

    now = now or timezone.now()

    if job.work_state == 'IN_PRODUCTION':
        stage = 'press'
    elif job.work_state in ('FINISHING', 'QUALITY_CHECK'):
        stage = 'finishing'
    else:
        return None

    steps = list(
        JobStep.objects
        .filter(job=job)
        .select_related('job__branch', 'machine', 'station', 'line_item')
        .order_by('line_item_id', 'sequence')
    )
    if not steps:
        return None

    by_line = {}
    for s in steps:
        by_line.setdefault(s.line_item_id, []).append(s)

    finish = 0.0
    any_over = False
    any_held = False
    anything_left = False

    for line_steps in by_line.values():
        remaining = [s for s in line_steps if s.state != JobStep.State.DONE]
        if not remaining:
            continue

        # How far this stage reaches on this line: its print steps for
        # In press, everything for Finishing.
        if stage == 'press':
            last_print = max(
                (i for i, s in enumerate(remaining) if s.station.code == 'PRINT'),
                default=None,
            )
            if last_print is None:
                continue
            reach = remaining[:last_print + 1]
        else:
            reach = remaining

        anything_left = True
        t, over, held = _finish_of_current(reach[0], now)
        for later in reach[1:]:
            t += float(later.expected_minutes)

        finish = max(finish, t)
        any_over = any_over or over
        any_held = any_held or held

    if not anything_left:
        return None

    service = PredictionService(job.branch)
    start = service._next_working_moment(timezone.localtime(now))
    ready_at = service._add_working_minutes(start, finish)

    return StageEstimate(
        stage        = stage,
        minutes_left = round_up(finish),
        ready_at     = ready_at,
        running_over = any_over,
        held_up      = any_held,
    )

def job_ready_at(job, now=None):
    """
    When the whole job will be ready: every remaining step, not only the
    current stage's. The same pieces as estimate() (time left on the
    machine, the steps after it, opening hours walked), so there is
    still one way of estimating. A job with no steps yet (waiting for
    inspection) is asked of the prediction service, as its first promise
    was. None where nothing can be said.
    """
    from apps.production.services.prediction_service import PredictionService

    now = now or timezone.now()
    service = PredictionService(job.branch)

    if job.work_state in ('IN_PRODUCTION', 'FINISHING', 'QUALITY_CHECK'):
        steps = list(
            JobStep.objects.filter(job=job)
            .select_related('job__branch', 'machine', 'station', 'line_item')
            .order_by('line_item_id', 'sequence')
        )
        if steps:
            by_line = {}
            for s in steps:
                by_line.setdefault(s.line_item_id, []).append(s)
            finish = 0.0
            for line_steps in by_line.values():
                remaining = [s for s in line_steps if s.state != JobStep.State.DONE]
                if not remaining:
                    continue
                t, _over, _held = _finish_of_current(remaining[0], now)
                for later in remaining[1:]:
                    t += float(later.expected_minutes)
                finish = max(finish, t)
            if finish <= 0:
                return now   # only the final check is left
            start = service._next_working_moment(timezone.localtime(now))
            return service._add_working_minutes(start, finish)

    lines = []
    for item in job.line_items.filter(parent__isnull=True).select_related('service'):
        if item.service_id:
            lines.append((item.service, int(item.quantity or 1), int(getattr(item, 'pages', 1) or 1)))
    if not lines:
        return None
    try:
        return service.predict(lines, at=now).ready_at
    except Exception:
        return None