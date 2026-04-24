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

    cash  = get_method_total(completed, 'CASH')
    momo  = get_method_total(completed, 'MOMO')
    pos   = get_method_total(completed, 'POS')
    total = cash + momo + pos

    return {
        'cash'     : cash,
        'momo'     : momo,
        'pos'      : pos,
        'total'    : total,
        'job_count': completed.count(),
    }


def get_sheet_live_totals(sheet) -> dict:
    """
    Compute live revenue totals for an OPEN sheet directly from jobs.
    Called by DailySalesSheetTodayView for open sheets.
    """
    from apps.jobs.models import Job

    jobs = Job.objects.filter(
        daily_sheet=sheet,
        status=Job.COMPLETE,
    )

    breakdown = get_revenue_breakdown(jobs)

    return {
        'total_cash'        : breakdown['cash'],
        'total_momo'        : breakdown['momo'],
        'total_pos'         : breakdown['pos'],
        'total_collected'   : breakdown['total'],
        'net_cash_in_till'  : breakdown['cash'],
        'total_jobs_created': breakdown['job_count'],
    }


def get_cashier_summary(branch, date) -> dict:
    """
    Compute today payment totals per method for a branch cashier strip.
    Called by CashierSummaryView.
    """
    from apps.jobs.models import Job
    from apps.finance.models import PaymentLeg, CreditPayment, DailySalesSheet
    from django.db.models import Count

    jobs = Job.objects.filter(
        branch=branch,
        status=Job.COMPLETE,
        updated_at__date=date,
        amount_paid__isnull=False,
    )

    def _method_total(method):
        direct = jobs.filter(payment_method=method).aggregate(
            total=Sum('amount_paid'),
            count=Count('id'),
        )
        direct_total = Decimal(str(direct['total'] or 0))
        direct_count = direct['count'] or 0

        split_jobs = jobs.filter(payment_method='SPLIT')
        leg_total = PaymentLeg.objects.filter(
            job__in=split_jobs,
            payment_method=method,
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

        return {
            'total': str(direct_total + Decimal(str(leg_total))),
            'count': direct_count,
        }

    try:
        sheet = DailySalesSheet.objects.get(
            branch=branch, date=date, status='OPEN'
        )
        settlements = CreditPayment.objects.filter(daily_sheet=sheet)

        def _settle(method):
            r = settlements.filter(payment_method=method).aggregate(
                total=Sum('amount'),
                count=Count('id'),
            )
            return {'total': Decimal(str(r['total'] or 0)), 'count': r['count'] or 0}

        s_cash = _settle('CASH')
        s_momo = _settle('MOMO')
        s_pos  = _settle('POS')
    except DailySalesSheet.DoesNotExist:
        s_cash = s_momo = s_pos = {'total': Decimal('0'), 'count': 0}

    def _combine(job_t, settle_t):
        return {
            'total': str(Decimal(job_t['total']) + Decimal(str(settle_t['total']))),
            'count': job_t['count'] + settle_t['count'],
        }

    j_cash = _method_total('CASH')
    j_momo = _method_total('MOMO')
    j_pos  = _method_total('POS')

    cash  = _combine(j_cash, s_cash)
    momo  = _combine(j_momo, s_momo)
    pos   = _combine(j_pos,  s_pos)
    grand = Decimal(cash['total']) + Decimal(momo['total']) + Decimal(pos['total'])
    count = cash['count'] + momo['count'] + pos['count']

    return {
        'CASH' : cash,
        'MOMO' : momo,
        'POS'  : pos,
        'total': {'total': str(grand), 'count': count},
    }