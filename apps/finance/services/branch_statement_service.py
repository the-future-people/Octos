"""
BranchStatementService
=======================
Generates investor/bank-presentable financial statements for a branch
over an arbitrary date range, scoped by calendar week for the detail
table.

Access to this service is gated at the view level — not every BM
should be able to generate one. See api.views.BranchStatementView.

Source of truth: Receipt (actual payments collected), Job (volume),
CustomerProfile (registration growth). Never estimated_cost — always
amount_paid, consistent with the rest of the platform.
"""

import logging
from decimal import Decimal
from datetime import timedelta

logger = logging.getLogger(__name__)


class BranchStatementService:

    @staticmethod
    def generate(branch, date_from, date_to) -> dict:
        """
        Build the full statement payload for a branch between two dates
        (inclusive). Returns a dict consumed by the PDF builder.
        """
        summary   = BranchStatementService._build_summary(branch, date_from, date_to)
        weekly    = BranchStatementService._build_weekly_breakdown(branch, date_from, date_to)
        methods   = BranchStatementService._build_payment_methods(branch, date_from, date_to)
        growth    = BranchStatementService._build_customer_growth(branch, date_from, date_to)
        monthly   = BranchStatementService._build_monthly_trend(branch, date_from, date_to)

        return {
            'branch'     : branch,
            'date_from'  : date_from,
            'date_to'    : date_to,
            'summary'    : summary,
            'weekly'     : weekly,
            'methods'    : methods,
            'growth'     : growth,
            'monthly'    : monthly,
        }

    # ── Summary ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_summary(branch, date_from, date_to) -> dict:
        from apps.finance.models import Receipt
        from apps.jobs.models import Job
        from django.db.models import Sum, Count

        receipts = Receipt.objects.filter(
            daily_sheet__branch = branch,
            created_at__date__gte = date_from,
            created_at__date__lte = date_to,
            is_void = False,
        )

        agg = receipts.aggregate(
            total_revenue = Sum('amount_paid'),
            total_jobs    = Count('id'),
        )
        total_revenue = agg['total_revenue'] or Decimal('0')
        total_jobs    = agg['total_jobs'] or 0

        customer_count = Job.objects.filter(
            branch = branch,
            created_at__date__gte = date_from,
            created_at__date__lte = date_to,
            customer__isnull = False,
        ).values('customer').distinct().count()

        avg_job_value = (total_revenue / total_jobs) if total_jobs > 0 else Decimal('0')

        # Prior period of equal length, for growth comparison
        period_days = (date_to - date_from).days + 1
        prior_to    = date_from - timedelta(days=1)
        prior_from  = prior_to - timedelta(days=period_days - 1)

        prior_revenue = Receipt.objects.filter(
            daily_sheet__branch = branch,
            created_at__date__gte = prior_from,
            created_at__date__lte = prior_to,
            is_void = False,
        ).aggregate(t=Sum('amount_paid'))['t'] or Decimal('0')

        growth_pct = None
        if prior_revenue > 0:
            growth_pct = round(((total_revenue - prior_revenue) / prior_revenue) * 100, 1)

        return {
            'total_revenue' : total_revenue,
            'total_jobs'    : total_jobs,
            'customer_count': customer_count,
            'avg_job_value' : round(avg_job_value, 2),
            'growth_pct'    : growth_pct,
            'period_days'   : period_days,
        }

    # ── Weekly breakdown ──────────────────────────────────────────────────────

    @staticmethod
    def _build_weekly_breakdown(branch, date_from, date_to) -> list:
        """
        Calendar-week aligned breakdown (Monday-Sunday), clipped to the
        requested date range at both ends.
        """
        from apps.finance.models import Receipt
        from django.db.models import Sum, Count

        weeks = []
        cursor = date_from - timedelta(days=date_from.weekday())  # back to Monday

        while cursor <= date_to:
            week_start = max(cursor, date_from)
            week_end   = min(cursor + timedelta(days=6), date_to)

            receipts = Receipt.objects.filter(
                daily_sheet__branch = branch,
                created_at__date__gte = week_start,
                created_at__date__lte = week_end,
                is_void = False,
            )
            agg = receipts.aggregate(
                revenue = Sum('amount_paid'),
                jobs    = Count('id'),
            )
            revenue = agg['revenue'] or Decimal('0')
            jobs    = agg['jobs'] or 0
            avg_val = (revenue / jobs) if jobs > 0 else Decimal('0')

            weeks.append({
                'week_start' : week_start,
                'week_end'   : week_end,
                'revenue'    : revenue,
                'jobs'       : jobs,
                'avg_value'  : round(avg_val, 2),
            })

            cursor += timedelta(days=7)

        return weeks

    # ── Payment methods ───────────────────────────────────────────────────────

    @staticmethod
    def _build_payment_methods(branch, date_from, date_to) -> list:
        from apps.finance.models import Receipt
        from django.db.models import Sum

        receipts = Receipt.objects.filter(
            daily_sheet__branch = branch,
            created_at__date__gte = date_from,
            created_at__date__lte = date_to,
            is_void = False,
        )

        total = receipts.aggregate(t=Sum('amount_paid'))['t'] or Decimal('0')

        methods = []
        for method, label in Receipt.PaymentMethod.choices:
            amt = receipts.filter(payment_method=method).aggregate(
                t=Sum('amount_paid')
            )['t'] or Decimal('0')
            if amt > 0:
                pct = round((amt / total) * 100) if total > 0 else 0
                methods.append({'label': label, 'amount': amt, 'pct': pct})

        return sorted(methods, key=lambda m: m['amount'], reverse=True)

    # ── Customer growth ───────────────────────────────────────────────────────

    @staticmethod
    def _build_customer_growth(branch, date_from, date_to) -> dict:
        from apps.customers.models import CustomerProfile
        from apps.jobs.models import Job
        from apps.finance.models import CreditAccount

        new_customers = CustomerProfile.objects.filter(
            preferred_branch = branch,
            created_at__date__gte = date_from,
            created_at__date__lte = date_to,
        ).count()

        # Repeat customer rate — customers in this period with visit_count > 1
        jobs_in_period = Job.objects.filter(
            branch = branch,
            created_at__date__gte = date_from,
            created_at__date__lte = date_to,
            customer__isnull = False,
        ).select_related('customer')

        customer_ids = set(jobs_in_period.values_list('customer_id', flat=True))
        repeat_count = CustomerProfile.objects.filter(
            id__in=customer_ids, visit_count__gt=1
        ).count()
        repeat_rate = round((repeat_count / len(customer_ids)) * 100) if customer_ids else 0

        from django.db.models import F

        credit_accounts = CreditAccount.objects.filter(branch=branch, status='ACTIVE')
        credit_total    = credit_accounts.count()
        # "Good standing" = utilisation under 90% of limit
        credit_good     = credit_accounts.filter(
            current_balance__lte=F('credit_limit') * 0.9
        ).count() if credit_total else 0

        return {
            'new_customers'      : new_customers,
            'repeat_rate'        : repeat_rate,
            'credit_accounts_ok' : credit_good,
            'credit_accounts_total': credit_total,
        }

    # ── Monthly trend (for the bar chart on page 1) ───────────────────────────

    @staticmethod
    def _build_monthly_trend(branch, date_from, date_to) -> list:
        from apps.finance.models import Receipt
        from django.db.models import Sum
        from django.db.models.functions import TruncMonth

        receipts = Receipt.objects.filter(
            daily_sheet__branch = branch,
            created_at__date__gte = date_from,
            created_at__date__lte = date_to,
            is_void = False,
        ).annotate(month=TruncMonth('created_at')).values('month').annotate(
            revenue=Sum('amount_paid')
        ).order_by('month')

        return [
            {'label': r['month'].strftime('%b'), 'revenue': r['revenue'] or Decimal('0')}
            for r in receipts
        ]