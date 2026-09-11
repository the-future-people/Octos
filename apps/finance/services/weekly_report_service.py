# apps/finance/services/weekly_report_service.py

import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class WeeklyReportService:

    # Weeks ending on or after this date must be filed, and the branch
    # manager is blocked until they are. Weeks before it are history and
    # left alone — the branch has traded since March, and a mandatory
    # modal that opens on something from May is a bad way to meet a new
    # rule.
    #
    # A fixed date rather than "recently", so the rule means the same
    # thing next year as it does today.
    ENFORCED_FROM = date(2026, 9, 7)

    @staticmethod
    def outstanding_week(branch, today=None):
        """
        The week this branch owes, or None.

        Returns the earliest week that has ended, falls inside the
        enforced period, and has not been submitted. A draft is prepared
        if none exists: the Saturday task is a convenience and must not
        be the thing everything depends on, so a week nobody prepared is
        still a week that can be filed.
        """
        from datetime import timedelta
        from apps.finance.models import DailySalesSheet, WeeklyReport

        if today is None:
            today = timezone.localdate()

        # Walk back week by week from the last completed one. Bounded by
        # the enforced date, so this is a handful of iterations rather
        # than a scan over everything the branch has ever traded.
        monday = today - timedelta(days=today.weekday())
        cursor = monday - timedelta(days=7)

        outstanding = None
        while cursor >= WeeklyReportService.ENFORCED_FROM:
            saturday = cursor + timedelta(days=5)

            # A week nobody traded in is not owed. Sheets alone do not
            # mean trading: one opens every morning whether anyone comes
            # in or not.
            traded = DailySalesSheet.objects.filter(
                branch=branch, date__range=[cursor, saturday],
            ).exclude(total_jobs_created=0).exists()

            if traded:
                # A week split by a month boundary is two filings, one in
                # each month. Checking only the Monday's month would find
                # the first half and pass while the second was never
                # filed at all.
                months = {cursor.month, saturday.month}
                filed = WeeklyReport.objects.filter(
                    branch      = branch,
                    year        = cursor.isocalendar()[0],
                    week_number = cursor.isocalendar()[1],
                    month__in   = months,
                ).exclude(status=WeeklyReport.Status.DRAFT).count()

                if filed < len(months):
                    outstanding = cursor

            cursor -= timedelta(days=7)

        if outstanding is None:
            return None

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

        # The rule exists to stop a week being filed before it has
        # finished, and it reads the calendar to work that out. A week that
        # ended weeks ago has plainly finished, but the calendar says
        # nothing about it — so a week whose Saturday passed unfiled could
        # never be filed at all, and the month behind it never closed.
        #
        # Past weeks are judged on whether they are over. The current week
        # still answers to Saturday or the month end, because a week in
        # progress can look complete on a quiet Wednesday.
        week_has_ended = report.date_to < today

        if not week_has_ended and not is_saturday and not is_month_end:
            return None, [
                'This week is not finished. It can be submitted on '
                'Saturday, or on the last day of the month.'
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
        report.total_jobs_complete   = week_jobs.filter(status='COMPLETE').count()
        report.total_jobs_cancelled  = week_jobs.filter(status='CANCELLED').count()
        report.carry_forward_count   = week_jobs.filter(status='PENDING_PAYMENT').count()
        report.total_jobs_registered = week_jobs.exclude(customer__isnull=True).count()
        report.total_jobs_walkin     = week_jobs.filter(customer__isnull=True).count()

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

        # A week split by a month boundary is filed twice — the days in the
        # old month, and the days in the new one. Both carry the same ISO
        # week number, so the month is what tells them apart. Without it the
        # second half would find the first and overwrite its dates, and the
        # days in the earlier month would belong to no filing at all.
        report, created = WeeklyReport.objects.get_or_create(
            branch      = branch,
            week_number = week_number,
            year        = year,
            month       = effective_from.month,
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

        # Bounded by the report's own dates, not the calendar week: a
        # report covering the last three days of a month must not count
        # jobs from the days that belong to the next one's filing.
        week_jobs = Job.objects.filter(
            branch                  = branch,
            created_at__date__range = [effective_from, effective_to],
        )
        report.total_jobs_complete   = week_jobs.filter(status='COMPLETE').count()
        report.total_jobs_cancelled  = week_jobs.filter(status='CANCELLED').count()
        report.carry_forward_count   = week_jobs.filter(status='PENDING_PAYMENT').count()
        report.total_jobs_registered = week_jobs.exclude(customer__isnull=True).count()
        report.total_jobs_walkin     = week_jobs.filter(customer__isnull=True).count()

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