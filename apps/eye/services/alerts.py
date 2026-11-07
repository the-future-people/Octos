"""
What needs the owner, most serious first.

Red: money or customers at risk, or something stopped. Amber: something
slipping. One engine, so the Overview, every lens and (later) the texts
to the owner all say the same thing.

Each alert: level, kind, title, where, since (ISO or ''), and a link
{lens, id} to the thing it is about.
"""

from datetime import datetime, timedelta

from django.utils import timezone

from . import health, people

RED, AMBER = 'red', 'amber'


def _a(level, kind, title, where='', since=None, lens='', target=None):
    return {'level': level, 'kind': kind, 'title': title, 'where': where,
            'since': since.isoformat() if since else '', 'lens': lens, 'target': target}


def compute(scope, day=None) -> list:
    from apps.finance.models import CreditAccount, DailySalesSheet
    from apps.jobs.models import Job, JobHalt
    from apps.production.models import Machine

    now = timezone.now()
    today = timezone.localdate()
    day = day or today
    ids = scope.branch_ids
    out = []

    # Paid online and no job: the failure that hid order 43 for hours.
    for o in health.paid_without_job():
        if scope.kind == 'company' or o.branch_id in ids:
            out.append(_a(RED, 'paid_no_job', f'Paid order {o.order_number} has no job',
                          o.branch.name if o.branch_id else 'Not routed', o.paid_at, 'health'))

    # Machines down.
    for m in Machine.objects.filter(branch_id__in=ids, is_active=True, is_available=False).select_related('branch'):
        mins = (now - m.unavailable_since).total_seconds() / 60 if m.unavailable_since else 0
        level = RED if mins >= 60 else AMBER
        out.append(_a(level, 'machine_down', f'{m.name} down', m.branch.name,
                      m.unavailable_since, 'machines', m.pk))

    # Repeated breakdowns this month.
    from .machines import breakdowns
    first, _ = day.replace(day=1), day
    from . import periods
    m_start, m_end = periods.bounds(first, day)
    bd = breakdowns(list(Machine.objects.filter(branch_id__in=ids).values_list('id', flat=True)), m_start, m_end)
    names = dict(Machine.objects.filter(pk__in=bd.keys()).values_list('id', 'name'))
    for mid, moments in bd.items():
        if len(moments) >= 3:
            out.append(_a(RED, 'breakdowns', f'{names.get(mid, "A machine")}: {len(moments)} breakdowns this month',
                          '', None, 'machines', mid))

    # Jobs halted more than a day.
    for h in (JobHalt.objects.filter(job__branch_id__in=ids, resumed_at__isnull=True,
                                     halted_at__lt=now - timedelta(days=1))
              .select_related('job__branch')):
        out.append(_a(RED, 'halted_long', f'{h.job.job_number} halted over a day',
                      h.job.branch.name, h.halted_at, 'jobs', h.job_id))

    # Jobs past their promise.
    late = (Job.objects.filter(branch_id__in=ids, promise_state='LATE')
            .exclude(status__in=['CANCELLED', 'VOIDED']).exclude(handover_state='HANDED_OVER'))
    n_late = late.count()
    if n_late:
        out.append(_a(AMBER, 'late_jobs', f'{n_late} job{"s" if n_late > 1 else ""} past their promise',
                      '', None, 'jobs'))

    # Credit at its limit.
    for a in CreditAccount.objects.filter(branch_id__in=ids, status='ACTIVE').select_related('customer', 'branch'):
        if a.is_over_limit:
            out.append(_a(RED, 'credit_limit', f'{a.organisation_name or a.customer.display_name}: credit limit reached',
                          a.branch.name if a.branch_id else '', None, 'customers', a.customer_id))

    # Today only: sheets left open, people absent, repeated lateness.
    if day == today:
        local = timezone.localtime()
        for s in DailySalesSheet.objects.filter(branch_id__in=ids, date=today, status='OPEN').select_related('branch'):
            from apps.organization.services import hours
            closing = timezone.make_aware(datetime.combine(today, hours.hours_on(s.branch, today)[1]))
            if local > closing + timedelta(minutes=30):
                out.append(_a(AMBER, 'sheet_open', 'Cash sheet still open after closing',
                              s.branch.name, closing, 'money'))

        users = list(people.staff(ids))
        ledger = people.Ledger(users, today, today)
        absent = {}
        for u in users:
            if ledger.status(u, today)[0] == people.ABSENT:
                absent.setdefault(u.branch.name, []).append(u.full_name)
        for branch, names_ in absent.items():
            out.append(_a(AMBER, 'absent', f'{len(names_)} absent: {", ".join(names_[:3])}',
                          branch, None, 'people'))
        for u, n in people.late_three_times(ids, today):
            out.append(_a(AMBER, 'late_repeated', f'{u.full_name} late {n} times this week',
                          u.branch.name if u.branch_id else '', None, 'people', u.pk))

    out.sort(key=lambda a: (0 if a['level'] == RED else 1, a['since'] or '9'))
    return out


def score(alerts) -> int:
    """100, less 12 for each red and 5 for each amber, never below 40."""
    red = sum(1 for a in alerts if a['level'] == RED)
    amber = len(alerts) - red
    return max(40, 100 - red * 12 - amber * 5)


def colour(alerts) -> str:
    if any(a['level'] == RED for a in alerts):
        return 'red'
    return 'amber' if alerts else 'green'
