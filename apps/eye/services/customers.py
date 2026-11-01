"""
Customers: who they are, how much they spend, how they order, and which
ones need attention.

A customer belongs to the branch where they were first recorded. Many
are recorded with no branch at all (the website and the app come before
any branch), so a customer with no branch belongs to the branches of
their jobs. The whole company counts everyone; customers with no branch
and no jobs yet are counted there and named, so the total always adds up.

Gone quiet means a customer in the top tenth by spend whose last job is
older than twice their usual gap between jobs.
"""

from datetime import timedelta

from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone

from . import periods

NODE_LIMIT = 40


def customers(scope):
    from apps.customers.models import CustomerProfile
    if scope.kind == 'company':
        return CustomerProfile.objects.all()
    ids = (CustomerProfile.objects
           .filter(Q(branch_id__in=scope.branch_ids)
                   | Q(branch__isnull=True, jobs__branch_id__in=scope.branch_ids))
           .values_list('id', flat=True).distinct())
    return CustomerProfile.objects.filter(id__in=ids)


def unplaced():
    """No branch on the record and no job anywhere yet."""
    from apps.customers.models import CustomerProfile
    return CustomerProfile.objects.filter(branch__isnull=True, jobs__isnull=True).count()


def app_customer_ids(customer_ids) -> set:
    from apps.storefront.models import AppSession
    try:
        return set(AppSession.objects.filter(lead__customer_id__in=customer_ids)
                   .values_list('lead__customer_id', flat=True))
    except Exception:
        return set()


def gone_quiet(c, last, first, jobs, now):
    if not last or jobs < 3 or not first:
        return False
    usual = (last - first) / max(1, jobs - 1)
    return (now - last) > max(usual * 2, timedelta(days=7))


def lens(scope, first_day, last_day) -> dict:
    from apps.finance.models import CreditAccount

    qs = customers(scope)
    now = timezone.now()
    start, end = periods.bounds(first_day, last_day)

    top = list(qs.annotate(last=Max('jobs__created_at'), first=Min('jobs__created_at'),
                           n=Count('jobs'),
                           online=Count('jobs', filter=Q(jobs__intake_channel='ONLINE')),
                           counter=Count('jobs', filter=~Q(jobs__intake_channel='ONLINE')))
               .order_by('-total_spend')[:NODE_LIMIT])
    ids = [c.pk for c in top]
    with_app = app_customer_ids(ids)
    credit = {a.customer_id: a for a in CreditAccount.objects.filter(customer_id__in=ids, status='ACTIVE')}

    spends = sorted((float(c.total_spend) for c in qs.only('total_spend')), reverse=True)
    cutoff = spends[max(0, len(spends) // 10 - 1)] if spends else 0

    nodes = []
    for c in top:
        acct = credit.get(c.pk)
        if acct and acct.is_over_limit:
            state = 'credit_limit'
        elif c.created_at >= now - timedelta(days=7):
            state = 'new'
        elif float(c.total_spend) >= cutoff and gone_quiet(c, c.last, c.first, c.n, now):
            state = 'quiet'
        else:
            state = 'regular'
        nodes.append({
            'id': c.pk, 'name': c.display_name,
            'business': c.customer_type != 'INDIVIDUAL',
            'spend': c.total_spend, 'visits': c.visit_count,
            'channels': {'counter': c.counter > 0, 'online': c.online > 0, 'app': c.pk in with_app},
            'state': state,
            'last_job': c.last.isoformat() if c.last else None,
        })

    new = qs.filter(created_at__gte=start, created_at__lt=end).count()
    from apps.jobs.models import Job
    returning = (Job.objects.filter(branch_id__in=scope.branch_ids, created_at__gte=start,
                                    created_at__lt=end, customer__created_at__lt=start)
                 .values('customer_id').distinct().count())
    accounts = CreditAccount.objects.filter(branch_id__in=scope.branch_ids, status='ACTIVE')
    return {
        'customers': nodes,
        'total': qs.count(),
        'not_tied_to_a_branch': unplaced() if scope.kind == 'company' else None,
        'people': qs.filter(customer_type='INDIVIDUAL').count(),
        'businesses': qs.exclude(customer_type='INDIVIDUAL').count(),
        'new': new, 'returning': returning,
        'credit': {'accounts': accounts.count(),
                   'owed': accounts.aggregate(s=Sum('current_balance'))['s'] or 0,
                   'at_limit': sum(1 for a in accounts if a.is_over_limit)},
        'hubs': {'counter': sum(1 for n in nodes if n['channels']['counter']),
                 'online': sum(1 for n in nodes if n['channels']['online']),
                 'app': sum(1 for n in nodes if n['channels']['app'])},
    }


def customer(customer_id) -> dict:
    from apps.customers.models import CustomerProfile
    from apps.finance.models import CreditAccount

    c = CustomerProfile.objects.select_related('branch').get(pk=customer_id)
    jobs = c.jobs.exclude(status__in=['DRAFT', 'VOIDED']).order_by('-created_at')
    agg = jobs.aggregate(first=Min('created_at'), last=Max('created_at'), n=Count('id'))
    acct = CreditAccount.objects.filter(customer=c).first()
    sent_back = jobs.filter(final_checks__outcome='SENT_BACK').distinct().count()
    gap = None
    if agg['n'] and agg['n'] > 1:
        gap = round((agg['last'] - agg['first']).days / (agg['n'] - 1))
    return {
        'id': c.pk, 'name': c.display_name, 'business': c.customer_type != 'INDIVIDUAL',
        'phone': c.phone, 'branch': c.branch.name if c.branch_id else '',
        'since': c.created_at.date().isoformat(),
        'spend': c.total_spend, 'visits': c.visit_count, 'usual_gap_days': gap,
        'last_job': agg['last'].isoformat() if agg['last'] else None,
        'credit': ({'limit': acct.credit_limit, 'owed': acct.current_balance,
                    'over_limit': acct.is_over_limit} if acct else None),
        'sent_back': sent_back,
        'jobs': [{'id': j.pk, 'code': j.job_number, 'title': j.title,
                  'amount': j.amount_paid, 'at': j.created_at.isoformat(),
                  'state': j.handover_state if j.handover_state == 'HANDED_OVER' else j.work_state}
                 for j in jobs[:25]],
    }
