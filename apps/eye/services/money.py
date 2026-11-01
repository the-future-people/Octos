"""
Money in, from the records that hold it.

Receipts are the truth for what was collected, counter and online alike
(an online payment is receipted as ONLINE). A receipt belongs to the
branch of its sheet, or, when it landed while the branch was shut and
has no sheet yet, to the branch of its job.

Costs are not recorded in Octos yet, so the Eye says so rather than
showing a profit it cannot stand behind.
"""

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate

ZERO = Decimal('0')


def receipts(branch_ids, start, end):
    from apps.finance.models import Receipt
    return Receipt.objects.filter(
        Q(daily_sheet__branch_id__in=branch_ids)
        | Q(daily_sheet__isnull=True, job__branch_id__in=branch_ids),
        is_void=False,
        created_at__gte=start, created_at__lt=end,
    )


def collected(branch_ids, start, end) -> Decimal:
    return receipts(branch_ids, start, end).aggregate(s=Sum('amount_paid'))['s'] or ZERO


def online_orders_paid(branch_ids, start, end):
    from apps.storefront.models import OnlineOrder
    return OnlineOrder.objects.filter(
        branch_id__in=branch_ids, paid_at__gte=start, paid_at__lt=end,
    )


def fees(branch_ids, start, end) -> Decimal:
    return online_orders_paid(branch_ids, start, end).aggregate(
        s=Sum('payment_fee'))['s'] or ZERO


def revenue_after_fees(branch_ids, start, end) -> Decimal:
    return collected(branch_ids, start, end) - fees(branch_ids, start, end)


def daily_revenue(branch_ids, start, end) -> dict:
    """{date: Decimal} for every day with money in."""
    rows = (receipts(branch_ids, start, end)
            .annotate(d=TruncDate('created_at'))
            .values('d').annotate(s=Sum('amount_paid')))
    return {r['d']: r['s'] or ZERO for r in rows}


def by_method(branch_ids, start, end) -> dict:
    rows = receipts(branch_ids, start, end).values('payment_method').annotate(
        s=Sum('amount_paid'), n=Count('id'))
    return {r['payment_method']: {'amount': r['s'] or ZERO, 'count': r['n']} for r in rows}


def sheets(branch_ids, first, last):
    from apps.finance.models import DailySalesSheet
    return DailySalesSheet.objects.filter(
        branch_id__in=branch_ids, date__gte=first, date__lte=last)


def owed(branch_ids) -> dict:
    """Balances still due on live jobs, and what credit customers owe."""
    from apps.finance.models import CreditAccount
    from apps.jobs.models import Job

    live = Job.objects.filter(
        branch_id__in=branch_ids, payment_state='DEPOSIT_PAID',
    ).exclude(status__in=['CANCELLED', 'VOIDED'])
    balances = ZERO
    for est, paid in live.values_list('estimated_cost', 'amount_paid'):
        if est is not None:
            balances += max(est - (paid or ZERO), ZERO)

    accounts = CreditAccount.objects.filter(
        branch_id__in=branch_ids, status='ACTIVE')
    owed_credit = accounts.aggregate(s=Sum('current_balance'))['s'] or ZERO
    at_limit = [a for a in accounts.select_related('customer') if a.is_over_limit]
    return {
        'job_balances': balances,
        'credit_owed': owed_credit,
        'credit_accounts': accounts.count(),
        'at_limit': len(at_limit),
    }


def lens(scope, first, last, prev_first, prev_last) -> dict:
    from . import periods
    ids = scope.branch_ids
    start, end = periods.bounds(first, last)
    p_start, p_end = periods.bounds(prev_first, prev_last)

    methods = by_method(ids, start, end)
    online = methods.get('ONLINE', {}).get('amount', ZERO)
    total = sum((m['amount'] for m in methods.values()), ZERO)
    counter = total - online
    fee = fees(ids, start, end)
    paid_orders = online_orders_paid(ids, start, end)
    net = paid_orders.aggregate(s=Sum('net_received'))['s'] or ZERO

    sh = sheets(ids, first, last)
    credit_issued = sh.aggregate(s=Sum('total_credit_issued'))['s'] or ZERO

    prev_total = collected(ids, p_start, p_end)

    from . import scope as scope_mod
    kids = scope_mod.children(scope)
    if kids:
        inflows = [{'key': k.key, 'name': k.name,
                    'amount': collected(k.branch_ids, start, end)} for k in kids]
    else:
        inflows = [{'key': None, 'name': 'Counter', 'amount': counter},
                   {'key': None, 'name': 'Online', 'amount': online},
                   {'key': None, 'name': 'Credit', 'amount': credit_issued}]

    return {
        'collected': total,
        'collected_change': periods.change(total, prev_total),
        'revenue_after_fees': total - fee,
        'inflows': inflows,
        'channels': {'counter': counter, 'online': online, 'credit_issued': credit_issued},
        'methods': {k: v['amount'] for k, v in methods.items()},
        'owed': owed(ids),
        'sheets': {
            'total': sh.count(),
            'closed': sh.exclude(status='OPEN').count(),
            'open': sh.filter(status='OPEN').count(),
            'refunds': sh.aggregate(s=Sum('total_refunds'))['s'] or ZERO,
        },
        # Costs are not yet recorded in Octos. Shown as a state, never a guess.
        'profit': {'state': 'NOT_TRACKED',
                   'note': 'Costs are not recorded in Octos yet, so profit cannot be shown.'},
        'reconciliation': [{
            'pair': 'Online receipts vs Paystack payouts',
            'octos': online, 'landed': net, 'gap': net - online,
            'expected': 'Paystack fees', 'fees': fee,
        }],
    }
