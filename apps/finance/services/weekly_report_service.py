# apps/finance/services/weekly_report_service.py

import logging
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class WeeklyReportService:

    @staticmethod
    @transaction.atomic
    def submit(report, submitted_by) -> tuple:
        """
        Finalise and lock a weekly report.
        Re-aggregates figures, refreshes inventory snapshot,
        locks the report, generates PDF.
        Returns (report, errors).
        """
        from apps.finance.models import DailySalesSheet, WeeklyReport
        from apps.jobs.models import Job
        from django.db.models import Sum

        if report.is_locked:
            return None, ['Already submitted.']

        today = timezone.localdate()
        import calendar
        last_day_of_month = today.replace(
            day=calendar.monthrange(today.year, today.month)[1]
        )
        is_saturday  = today.weekday() == 5
        is_month_end = today == last_day_of_month
        if not is_saturday and not is_month_end:
            return None, [
                'Weekly report can only be submitted on Saturday '
                'or the last day of the month.'
            ]

        if not report.daily_sheets.exists():
            return None, ['No daily sheets linked. Prepare the report first.']

        if not report.all_sheets_closed:
            open_dates = report.daily_sheets.filter(
                status=DailySalesSheet.Status.OPEN
            ).values_list('date', flat=True)
            dates = ', '.join(str(d) for d in open_dates)
            return None, [f'Cannot submit — sheets still open: {dates}']

        # ── Re-aggregate from closed sheets ───────────────────────────
        closed = report.daily_sheets.exclude(status=DailySalesSheet.Status.OPEN)

        report.total_cash           = closed.aggregate(t=Sum('total_cash'))['t']           or 0
        report.total_momo           = closed.aggregate(t=Sum('total_momo'))['t']           or 0
        report.total_pos            = closed.aggregate(t=Sum('total_pos'))['t']            or 0
        report.total_petty_cash_out = closed.aggregate(t=Sum('total_petty_cash_out'))['t'] or 0
        report.total_credit_issued  = closed.aggregate(t=Sum('total_credit_issued'))['t']  or 0
        report.net_cash_in_till     = closed.aggregate(t=Sum('net_cash_in_till'))['t']     or 0
        report.total_jobs_created   = closed.aggregate(t=Sum('total_jobs_created'))['t']   or 0

        week_jobs = Job.objects.filter(
            branch                  = report.branch,
            created_at__date__range = [report.date_from, report.date_to],
        )
        report.total_jobs_complete  = week_jobs.filter(status='COMPLETE').count()
        report.total_jobs_cancelled = week_jobs.filter(status='CANCELLED').count()
        report.carry_forward_count  = week_jobs.filter(status='PENDING_PAYMENT').count()

        # ── Refresh inventory snapshot ─────────────────────────────────
        try:
            from apps.inventory.inventory_engine import InventoryEngine
            report.inventory_snapshot = InventoryEngine(report.branch).generate_weekly_snapshot(
                date_from=report.date_from,
                date_to=report.date_to,
            )
        except Exception:
            logger.exception('WeeklyReportService: inventory snapshot failed for report %s', report.pk)

        # ── Lock ──────────────────────────────────────────────────────
        report.status       = report.Status.LOCKED
        report.submitted_by = submitted_by
        report.submitted_at = timezone.now()
        report.save()

        # ── Generate PDF ───────────────────────────────────────────────
        try:
            from apps.finance.api.views import _generate_weekly_pdf
            _generate_weekly_pdf(report)
        except Exception:
            logger.exception('WeeklyReportService: PDF generation failed for report %s', report.pk)

        return report, []

    @staticmethod
    def prepare(branch, today=None) -> tuple:
        """
        Create or refresh a DRAFT weekly report for the current week.
        Returns (report, created).
        """
        import calendar
        from datetime import timedelta
        from apps.finance.models import DailySalesSheet, WeeklyReport
        from apps.jobs.models import Job
        from django.db.models import Sum

        if today is None:
            today = timezone.localdate()

        monday   = today - timedelta(days=today.weekday())
        saturday = monday + timedelta(days=5)

        first_day_of_month = today.replace(day=1)
        last_day_of_month  = today.replace(
            day=calendar.monthrange(today.year, today.month)[1]
        )
        effective_from = max(monday,   first_day_of_month)
        effective_to   = min(saturday, last_day_of_month)

        week_number = today.isocalendar()[1]
        year        = today.isocalendar()[0]

        report, created = WeeklyReport.objects.get_or_create(
            branch      = branch,
            week_number = week_number,
            year        = year,
            defaults    = {
                'date_from': effective_from,
                'date_to'  : effective_to,
                'status'   : WeeklyReport.Status.DRAFT,
            }
        )

        sheets = DailySalesSheet.objects.filter(
            branch     = branch,
            date__range= [effective_from, effective_to],
        )
        report.date_from = effective_from
        report.date_to   = effective_to
        report.daily_sheets.set(sheets)

        closed = sheets.exclude(status=DailySalesSheet.Status.OPEN)
        report.total_cash           = closed.aggregate(t=Sum('total_cash'))['t']           or 0
        report.total_momo           = closed.aggregate(t=Sum('total_momo'))['t']           or 0
        report.total_pos            = closed.aggregate(t=Sum('total_pos'))['t']            or 0
        report.total_petty_cash_out = closed.aggregate(t=Sum('total_petty_cash_out'))['t'] or 0
        report.total_credit_issued  = closed.aggregate(t=Sum('total_credit_issued'))['t']  or 0
        report.net_cash_in_till     = closed.aggregate(t=Sum('net_cash_in_till'))['t']     or 0
        report.total_jobs_created   = closed.aggregate(t=Sum('total_jobs_created'))['t']   or 0

        week_jobs = Job.objects.filter(
            branch                  = branch,
            created_at__date__range = [monday, saturday],
        )
        report.total_jobs_complete  = week_jobs.filter(status='COMPLETE').count()
        report.total_jobs_cancelled = week_jobs.filter(status='CANCELLED').count()
        report.carry_forward_count  = week_jobs.filter(status='PENDING_PAYMENT').count()

        try:
            from apps.inventory.inventory_engine import InventoryEngine
            report.inventory_snapshot = InventoryEngine(branch).generate_weekly_snapshot(
                date_from=monday,
                date_to=saturday,
            )
        except Exception:
            logger.exception('WeeklyReportService: inventory snapshot failed during prepare')

        report.save()
        return report, created