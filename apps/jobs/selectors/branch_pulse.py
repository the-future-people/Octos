"""
The branch's pulse, for the strip across the top of the BM portal (15 Nov 2026).

Three real figures in place of the placeholders that were there:

  Floor load     Machine work still waiting, against the time the
                 working machines have left today. Over 100% means
                 today's queue won't finish today.
  Machines up    Active machines that are available, and why any are down.
  Promises kept  Of the jobs that turned ready in the last 7 days, how many
                 were ready by the first time promised (lateness.py scores
                 each one, kept or broken, when it turns ready).

Branch.current_load and capacity_score are not used: nothing has ever
kept them up to date.
"""
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

PROMISE_DAYS = 7
GONE = ('CANCELLED', 'VOIDED')
CACHE_SECONDS = 60


def branch_pulse(branch, now=None):
    from django.core.cache import cache

    key = f'pulse:branch:{branch.pk}'
    if now is None:
        cached = cache.get(key)
        if cached is not None:
            return cached
    result = _pulse(branch, now or timezone.now())
    if now is None:
        cache.set(key, result, CACHE_SECONDS)
    return result


def _pulse(branch, now):
    machines = _machines(branch)
    return {
        'floor': _floor(branch, now, machines['up']),
        'machines': machines,
        'promises': _promises(branch, now),
    }


def _machines(branch):
    from apps.production.models import Machine

    active = list(Machine.objects.filter(branch=branch, is_active=True)
                  .order_by('name').values('name', 'is_available', 'unavailable_reason'))
    down = [{'name': m['name'], 'reason': m['unavailable_reason']} for m in active if not m['is_available']]
    return {'up': len(active) - len(down), 'total': len(active), 'down': down}


def _floor(branch, now, machines_up):
    """
    {'state': 'open' | 'closed', 'percent': int or None, 'queued_minutes': int}.

    Waiting work is every machine step not yet done on a live job; work by
    hand has no machine to measure against, so it is left out. The time
    left runs from now (or opening, before the doors open) to closing.
    """
    from apps.jobs.models import JobStep
    from apps.organization.services import hours

    queued = (
        JobStep.objects
        .filter(job__branch=branch, by_hand=False)
        .exclude(state=JobStep.State.DONE)
        .exclude(job__status__in=GONE)
        .aggregate(total=Sum('expected_minutes'))['total']
    )
    queued = int(queued or 0)

    today = timezone.localdate(now)
    minutes_left = 0
    if hours.is_trading_day(branch, today):
        start = max(now, hours.opening_at(branch, today))
        minutes_left = max(0, int((hours.closing_at(branch, today) - start).total_seconds() // 60))

    if minutes_left == 0:
        return {'state': 'closed', 'percent': None, 'queued_minutes': queued}
    if machines_up == 0:
        return {'state': 'open', 'percent': None, 'queued_minutes': queued}
    return {'state': 'open', 'percent': round(queued * 100 / (machines_up * minutes_left)),
            'queued_minutes': queued}


def _promises(branch, now):
    from apps.jobs.models import Job, JobStatusLog
    from apps.jobs.services.lateness import BROKEN, KEPT

    ready_lately = (JobStatusLog.objects
                    .filter(job__branch=branch, axis=JobStatusLog.Axis.WORK, to_status='DONE',
                            transitioned_at__gte=now - timedelta(days=PROMISE_DAYS))
                    .values('job_id'))
    scored = Job.objects.filter(pk__in=ready_lately, promise_state__in=[KEPT, BROKEN])
    total = scored.count()
    kept = scored.filter(promise_state=KEPT).count()
    return {'kept': kept, 'total': total, 'days': PROMISE_DAYS,
            'percent': round(kept * 100 / total) if total else None}
