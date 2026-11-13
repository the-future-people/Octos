# apps/jobs/selectors/revenue_selectors.py
"""
Revenue selectors — single source of truth for all payment aggregations.

Every view, service, and engine that needs revenue totals calls these
functions. Never compute revenue inline in a view again.

Technical note: This is the "selector" pattern — pure read functions
that return data but never mutate state. They are the read side of
CQRS (Command Query Responsibility Segregation). Commands (writes) live
in services. Queries (reads) live here.
"""

from decimal import Decimal
from django.db.models import Sum


def get_method_total(jobs_qs, method: str) -> Decimal:
    """
    Return total amount_paid for a given payment method,
    including contributions from SPLIT payment legs.
    """
    from apps.finance.models import PaymentLeg

    direct = jobs_qs.filter(
        payment_method=method,
    ).aggregate(t=Sum('amount_paid'))['t'] or Decimal('0')

    split_jobs = jobs_qs.filter(payment_method='SPLIT')
    legs = PaymentLeg.objects.filter(
        job__in=split_jobs,
        payment_method=method,
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    return Decimal(str(direct)) + Decimal(str(legs))


def get_revenue_breakdown(jobs_qs) -> dict:
    """
    Return a full revenue breakdown for a queryset of completed jobs.
    Includes SPLIT leg resolution for all methods.
    """
    completed = jobs_qs.filter(
        status='COMPLETE',
        amount_paid__isnull=False,
    )

    from apps.finance import payment_methods as pm

    # "cash + momo + pos" was always shorthand for money the branch
    # actually received. The registry knows which methods those are, so a
    # new one is counted the day it is added instead of being left out of
    # the day's revenue with nobody told.
    by_method = {
        m.code: get_method_total(completed, m.code)
        for m in pm.METHODS if m.collected
    }

    out = {m.code.lower(): amount for m, amount in
           ((pm.get(code), amount) for code, amount in by_method.items())}
    out['total']     = sum(by_method.values(), Decimal('0'))
    out['job_count'] = completed.count()
    return out


# ── Money taken, from receipts (13 Nov 2026) ────────────────────────────────
# Money taken is what receipts say was handed over: each non-void receipt by
# its method, a split receipt by its legs. Totalling jobs instead counted a
# production payment nowhere (its status is PAID until collected), put a job
# paid by MoMo deposit and cash balance wholly under one method on one day,
# and counted an old job as today's money when it was edited today.

def add_rows(out, rows, total_key, method_key='payment_method'):
    """Add aggregated rows into {code: {'total', 'count'}}; methods not collected are skipped."""
    for row in rows:
        code = row[method_key]
        if code in out:
            out[code]['total'] += Decimal(str(row[total_key] or 0))
            out[code]['count'] += row['n'] or 0
    return out


def receipt_totals(receipts):
    """{method: {'total': Decimal, 'count': int}} for money collected, from receipts."""
    from django.db.models import Count
    from apps.finance import payment_methods as pm
    from apps.finance.models import PaymentLeg

    out = {m.code: {'total': Decimal('0'), 'count': 0} for m in pm.METHODS if m.collected}
    live = receipts.filter(is_void=False)
    add_rows(out, live.exclude(payment_method='SPLIT').values('payment_method')
             .annotate(t=Sum('amount_paid'), n=Count('id')), 't')
    add_rows(out, PaymentLeg.objects.filter(receipt__in=live.filter(payment_method='SPLIT'))
             .values('payment_method').annotate(t=Sum('amount'), n=Count('id')), 't')
    return out


def sheet_receipt_totals(sheet):
    from apps.finance.models import Receipt
    return receipt_totals(Receipt.objects.filter(daily_sheet=sheet))


def get_sheet_live_totals(sheet) -> dict:
    """
    Live revenue for an OPEN sheet, from its receipts.
    Called by DailySalesSheetTodayView for open sheets.
    """
    from apps.finance import payment_methods as pm
    from apps.finance.models import Receipt

    totals = sheet_receipt_totals(sheet)
    get = lambda code: totals.get(code, {'total': Decimal('0')})['total']
    in_till = sum((totals[m.code]['total'] for m in pm.METHODS if m.collected and m.in_till), Decimal('0'))
    paid_jobs = (Receipt.objects.filter(daily_sheet=sheet, is_void=False)
                 .exclude(job__isnull=True).values('job').distinct().count())
    return {
        'total_cash'        : get('CASH'),
        'total_momo'        : get('MOMO'),
        'total_pos'         : get('POS'),
        'total_collected'   : sum((v['total'] for v in totals.values()), Decimal('0')),
        'net_cash_in_till'  : in_till,
        'total_jobs_created': paid_jobs,
    }


def get_cashier_summary(branch, date) -> dict:
    """
    Today's money taken per method, for the cashier strip: the receipts on
    the branch's open sheet (or the day's receipts at the branch when no sheet
    is open), plus credit settlements, which are money in as well.
    """
    from django.db.models import Count
    from apps.finance.models import CreditPayment, DailySalesSheet, Receipt

    sheet = DailySalesSheet.objects.filter(branch=branch, date=date, status='OPEN').first()
    receipts = (Receipt.objects.filter(daily_sheet=sheet) if sheet
                else Receipt.objects.filter(daily_sheet__branch=branch, created_at__date=date))
    totals = receipt_totals(receipts)
    if sheet:
        add_rows(totals, CreditPayment.objects.filter(daily_sheet=sheet).values('payment_method')
                 .annotate(t=Sum('amount'), n=Count('id')), 't')

    zero = {'total': Decimal('0'), 'count': 0}
    shown = {code: totals.get(code, zero) for code in ('CASH', 'MOMO', 'POS')}
    grand = sum((v['total'] for v in shown.values()), Decimal('0'))
    count = sum(v['count'] for v in shown.values())
    out = {code: {'total': str(v['total']), 'count': v['count']} for code, v in shown.items()}
    out['total'] = {'total': str(grand), 'count': count}
    return out
