"""
Machines: up or down, how busy, who runs them, how often they break.

Busy is the work done on the machine today (the expected minutes of the
steps finished on it) over the minutes the branch has been open so far.

A breakdown is counted once per moment a machine was marked down: every
job queued on it is halted together, so the halts are grouped by machine
and minute. A dedicated downtime log replaces this once it exists.
"""

from datetime import datetime, timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMinute
from django.utils import timezone

from . import periods


def machines(branch_ids):
    from apps.production.models import Machine
    return (Machine.objects.filter(branch_id__in=branch_ids, is_active=True)
            .select_related('branch', 'machine_type'))


def operators(machine_ids) -> dict:
    from apps.production.models import MachineOperator
    out = {}
    for a in (MachineOperator.objects
              .filter(machine_id__in=machine_ids, active_until__isnull=True)
              .select_related('operator')):
        out.setdefault(a.machine_id, []).append({'id': a.operator_id, 'name': a.operator.full_name})
    return out


def breakdowns(machine_ids, start, end) -> dict:
    """{machine_id: [moment, ...]} of breakdowns in the window."""
    from apps.jobs.models import JobHalt
    rows = (JobHalt.objects
            .filter(machine_id__in=machine_ids, reason='MACHINE_BREAKDOWN',
                    halted_at__gte=start, halted_at__lt=end)
            .annotate(m=TruncMinute('halted_at'))
            .values('machine_id', 'm').distinct())
    out = {}
    for r in rows:
        out.setdefault(r['machine_id'], []).append(r['m'])
    return out


def open_minutes_so_far(branch, day):
    now = timezone.localtime()
    from apps.organization.services import hours
    opens, closes = hours.hours_on(branch, day)     # Saturday's own hours too
    opening = timezone.make_aware(datetime.combine(day, opens))
    closing = timezone.make_aware(datetime.combine(day, closes))
    end = min(now, closing) if day == now.date() else closing
    return max(0, (end - opening).total_seconds() / 60)


def card(m, ops, queue, busy_min, bd, day):
    open_min = open_minutes_so_far(m.branch, day)
    down_for = None
    if not m.is_available and m.unavailable_since:
        down_for = round((timezone.now() - m.unavailable_since).total_seconds() / 60)
    if not m.is_available:
        state = 'down'
    elif queue.get('active'):
        state = 'printing'
    else:
        state = 'idle'
    return {
        'id': m.pk, 'name': m.name, 'type': m.machine_type.name,
        'branch': m.branch.name, 'branch_id': m.branch_id,
        'state': state, 'down_minutes': down_for, 'down_reason': m.unavailable_reason,
        'operators': ops.get(m.pk, []),
        'queue': queue.get('waiting', 0) + queue.get('active', 0),
        'busy_pct': min(100, round(busy_min / open_min * 100)) if open_min else 0,
        'breakdowns_month': len(bd.get(m.pk, [])),
    }


def lens(scope, day) -> dict:
    from apps.jobs.models import JobStep

    ms = list(machines(scope.branch_ids))
    ids = [m.pk for m in ms]
    ops = operators(ids)

    queue = {}
    for r in (JobStep.objects.filter(machine_id__in=ids, state__in=['WAITING', 'ACTIVE'])
              .values('machine_id', 'state').annotate(n=Count('id'))):
        queue.setdefault(r['machine_id'], {})[r['state'].lower()] = r['n']

    start, end = periods.bounds(day, day)
    busy = dict(JobStep.objects.filter(machine_id__in=ids, done_at__gte=start, done_at__lt=end)
                .values_list('machine_id').annotate(s=Sum('expected_minutes')))
    m_start, m_end = periods.bounds(day.replace(day=1), day)
    bd = breakdowns(ids, m_start, m_end)

    cards = [card(m, ops, queue.get(m.pk, {}), float(busy.get(m.pk) or 0), bd, day) for m in ms]
    order = {'down': 0, 'printing': 1, 'idle': 2}
    cards.sort(key=lambda c: (order[c['state']], c['branch'], c['name']))

    by_type = {}
    for c in cards:
        by_type[c['type']] = by_type.get(c['type'], 0) + 1
    return {
        'machines': cards,
        'by_type': by_type,
        'up': sum(1 for c in cards if c['state'] != 'down'),
        'total': len(cards),
        'printing': sum(1 for c in cards if c['state'] == 'printing'),
        'idle': sum(1 for c in cards if c['state'] == 'idle'),
        'down': sum(1 for c in cards if c['state'] == 'down'),
        'with_operator': sum(1 for c in cards if c['operators']),
        'average_busy': round(sum(c['busy_pct'] for c in cards) / len(cards)) if cards else 0,
    }


def machine(machine_id, day) -> dict:
    from apps.jobs.models import JobStep
    from apps.production.models import Machine

    m = Machine.objects.select_related('branch', 'machine_type').get(pk=machine_id)
    first = day.replace(day=1)
    m_start, m_end = periods.bounds(first, day)
    bd = breakdowns([m.pk], m_start, m_end).get(m.pk, [])
    bd_days = {timezone.localtime(x).date() for x in bd}

    done = JobStep.objects.filter(machine=m, done_at__gte=m_start, done_at__lt=m_end)
    current = (JobStep.objects.filter(machine=m, state='ACTIVE')
               .select_related('job').first())
    queue = JobStep.objects.filter(machine=m, state__in=['WAITING', 'ACTIVE']).count()
    t_start, t_end = periods.bounds(day, day)
    busy_min = float(JobStep.objects.filter(machine=m, done_at__gte=t_start, done_at__lt=t_end)
                     .aggregate(s=Sum('expected_minutes'))['s'] or 0)

    base = card(m, operators([m.pk]), {'active': 1 if current else 0, 'waiting': queue},
                busy_min, {m.pk: bd}, day)
    calendar = []
    d = first
    while d <= day:
        calendar.append({'date': d.isoformat(), 'breakdown': d in bd_days})
        d += timedelta(days=1)
    return {
        **base,
        'now': current.job.title if current else None,
        'month': {'jobs': done.values('job_id').distinct().count(),
                  'made': done.aggregate(s=Sum('quantity_made'))['s'] or 0,
                  'spoilt': done.aggregate(s=Sum('quantity_spoilt'))['s'] or 0},
        'calendar': calendar,
        'breakdowns': [timezone.localtime(x).isoformat() for x in sorted(bd, reverse=True)],
        'commissioned_on': m.commissioned_on.isoformat() if m.commissioned_on else None,
        'price': None,   # purchase price is not recorded yet
        'repairs': None,
        'model_number': m.model_number,
    }
