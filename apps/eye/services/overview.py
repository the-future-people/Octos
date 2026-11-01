"""
The Overview: the focused place, its children, its health, its month.
"""

from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from . import alerts as alerts_mod
from . import jobs, money, people, periods
from . import scope as scope_mod

DIAL_DAYS = 30


def headline(sc, day) -> dict:
    """The four figures every level shows."""
    from apps.production.models import Machine
    start, end = periods.bounds(day, day)
    p_start, p_end = periods.bounds(day - timedelta(days=1), day - timedelta(days=1))
    rev = money.revenue_after_fees(sc.branch_ids, start, end)
    prev = money.revenue_after_fees(sc.branch_ids, p_start, p_end)
    users = list(people.staff(sc.branch_ids))
    ledger = people.Ledger(users, day, day)
    counts = people.today_counts([people.person_row(ledger, u, day) for u in users])
    ms = Machine.objects.filter(branch_id__in=sc.branch_ids, is_active=True)
    return {
        'revenue': rev, 'revenue_change': periods.change(rev, prev),
        'jobs': jobs.taken(sc.branch_ids, start, end).count(),
        'staff': counts,
        'machines': {'up': ms.filter(is_available=True).count(), 'total': ms.count()},
    }


def dial(sc, day) -> list:
    """
    One tick per day for the last 30 days: revenue, and the day's health
    from what was recorded that day. Red for a machine breakdown or a
    paid order left without a job; amber for a broken promise.
    """
    from apps.jobs.models import Job, JobHalt
    from apps.storefront.models import OnlineOrder

    first = day - timedelta(days=DIAL_DAYS - 1)
    start, end = periods.bounds(first, day)
    rev = money.daily_revenue(sc.branch_ids, start, end)

    def by_day(qs, field):
        return dict(qs.annotate(d=TruncDate(field)).values_list('d').annotate(n=Count('id')))

    breakdowns = by_day(JobHalt.objects.filter(job__branch_id__in=sc.branch_ids,
                                               reason='MACHINE_BREAKDOWN',
                                               halted_at__gte=start, halted_at__lt=end), 'halted_at')
    broken = by_day(Job.objects.filter(branch_id__in=sc.branch_ids, promise_state='BROKEN',
                                       first_promise_at__gte=start, first_promise_at__lt=end), 'first_promise_at')
    orphans = by_day(OnlineOrder.objects.filter(branch_id__in=sc.branch_ids, paid_at__gte=start,
                                                paid_at__lt=end, job__isnull=True), 'paid_at')
    out = []
    d = first
    while d <= day:
        red = breakdowns.get(d, 0) or orphans.get(d, 0)
        out.append({'date': d.isoformat(), 'revenue': rev.get(d, 0),
                    'health': 'red' if red else ('amber' if broken.get(d, 0) else 'green')})
        d += timedelta(days=1)
    return out


def build(sc, day) -> dict:
    al = alerts_mod.compute(sc, day)
    kids = []
    for k in scope_mod.children(sc):
        ka = alerts_mod.compute(k, day)
        h = headline(k, day)
        kids.append({**k.as_dict(), 'revenue': h['revenue'], 'jobs': h['jobs'],
                     'staff': h['staff'], 'machines': h['machines'],
                     'health': alerts_mod.score(ka), 'colour': alerts_mod.colour(ka),
                     'alerts': len(ka), 'branches': len(k.branch_ids)})

    start, end = periods.bounds(day, day)
    kept_pct, _, _ = jobs.promise_kept(sc.branch_ids, *periods.bounds(day.replace(day=1), day))
    sh = money.sheets(sc.branch_ids, day, day)
    return {
        'scope': sc.as_dict(),
        'path': scope_mod.path(sc),
        'day': day.isoformat(),
        'health': alerts_mod.score(al),
        'colour': alerts_mod.colour(al),
        'headline': headline(sc, day),
        'business': {
            'finished': jobs.finished(sc.branch_ids, start, end),
            'promises_kept_month': kept_pct,
            'sheets': {'closed': sh.exclude(status='OPEN').count(), 'total': sh.count()},
            'profit': {'state': 'NOT_TRACKED'},
        },
        'children': kids,
        'alerts': al,
        'dial': dial(sc, day),
    }
