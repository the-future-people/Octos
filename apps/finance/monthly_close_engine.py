# apps/finance/engines/monthly_close_engine.py

"""
MonthlyCloseEngine
==================
Handles all business logic for the End-of-Month Close process.

Responsibilities:
  - Integrity checks before BM can submit
  - Building the full month summary snapshot
  - Finance reviewer assignment (round-robin, HQ level)
  - Status transitions: submit, assign_finance, request_clarification,
    respond_clarification, clear, endorse, reject, lock
  - PDF generation (ReportLab)
"""

import logging
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from django.db import transaction

logger = logging.getLogger(__name__)


class MonthlyCloseEngine:

    def __init__(self, branch, month: int, year: int):
        self.branch = branch
        self.month  = month
        self.year   = year

    # ── Get or create ─────────────────────────────────────────────────────

    def get_or_create(self):
        from apps.finance.models import MonthlyClose
        close, created = MonthlyClose.objects.get_or_create(
            branch=self.branch,
            month=self.month,
            year=self.year,
        )
        return close, created

    # ── Integrity checks ──────────────────────────────────────────────────

    def check_integrity(self) -> dict:
        """
        Run all integrity checks required before BM can submit.
        Returns a dict with pass/fail per check and an overall can_submit bool.
        """
        from apps.finance.models import DailySalesSheet, WeeklyReport, CashierFloat
        from apps.jobs.models import Job

        first_day = date(self.year, self.month, 1)
        last_day  = date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

        checks = {}

        # 1. All daily sheets for the month must be closed
        open_sheets = DailySalesSheet.objects.filter(
            branch    = self.branch,
            date__gte = first_day,
            date__lte = last_day,
            status    = DailySalesSheet.Status.OPEN,
        )
        open_count = open_sheets.count()
        checks['all_sheets_closed'] = {
            'pass'  : open_count == 0,
            'label' : 'All daily sheets closed',
            'detail': f"{open_count} sheet(s) still open." if open_count else "All sheets closed.",
        }

        # 2. All weekly filings for the month must be submitted or locked
        draft_reports = WeeklyReport.objects.filter(
            branch         = self.branch,
            year           = self.year,
            status         = WeeklyReport.Status.DRAFT,
            date_from__gte = first_day,
            date_to__lte   = last_day,
        )
        draft_count = draft_reports.count()
        checks['all_weekly_filed'] = {
            'pass'  : draft_count == 0,
            'label' : 'All weekly filings submitted',
            'detail': f"{draft_count} weekly filing(s) still in draft." if draft_count else "All weekly filings submitted.",
        }

        # 3. No pending payment jobs from this month
        pending_jobs = Job.objects.filter(
            branch                = self.branch,
            status                = Job.PENDING_PAYMENT,
            created_at__date__gte = first_day,
            created_at__date__lte = last_day,
        )
        pending_count = pending_jobs.count()
        checks['no_pending_payments'] = {
            'pass'  : pending_count == 0,
            'label' : 'No pending payments',
            'detail': f"{pending_count} job(s) still pending payment." if pending_count else "No pending payments.",
        }

        # 4. No unsigned cashier floats from this month
        unsigned_floats = CashierFloat.objects.filter(
            daily_sheet__branch    = self.branch,
            daily_sheet__date__gte = first_day,
            daily_sheet__date__lte = last_day,
            is_signed_off          = False,
        )
        unsigned_count = unsigned_floats.count()
        checks['no_unsigned_floats'] = {
            'pass'  : unsigned_count == 0,
            'label' : 'All cashier floats signed off',
            'detail': f"{unsigned_count} float(s) not signed off." if unsigned_count else "All floats signed off.",
        }

        can_submit = all(c['pass'] for c in checks.values())

        return {
            'can_submit': can_submit,
            'checks'    : checks,
            'month'     : self.month,
            'year'      : self.year,
            'last_day'  : last_day.isoformat(),
        }

    # ── Finance reviewer assignment ───────────────────────────────────────

    def _assign_finance_reviewer(self, close):
        """
        Round-robin assignment across all active Finance role users (HQ level —
        branch is None). Picks the Finance user with the fewest assigned closes.
        """
        from apps.accounts.models import CustomUser
        from apps.finance.models import MonthlyClose
        from django.db.models import Count, Q

        finance_users = CustomUser.objects.filter(
            role__name='FINANCE',
            is_active=True,
            branch__isnull=True,
        ).annotate(
            assigned_count=Count(
                'monthly_closes_reviewing',
                filter=Q(monthly_closes_reviewing__status__in=[
                    MonthlyClose.Status.FINANCE_REVIEWING,
                    MonthlyClose.Status.NEEDS_CLARIFICATION,
                    MonthlyClose.Status.RESUBMITTED,
                ]),
            )
        ).order_by('assigned_count', 'id')

        return finance_users.first()

    # ── Snapshot ──────────────────────────────────────────────────────────

    def build_snapshot(self) -> dict:
        from apps.finance.models import DailySalesSheet, WeeklyReport, CashierFloat
        from apps.jobs.models import Job, JobLineItem
        from apps.inventory.models import StockMovement, WasteIncident
        from django.db.models import Sum, Count, Q

        first_day = date(self.year, self.month, 1)
        last_day  = date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

        sheets = DailySalesSheet.objects.filter(
            branch    = self.branch,
            date__gte = first_day,
            date__lte = last_day,
        ).order_by('date')

        # ── Revenue totals ────────────────────────────────────────────────
        total_cash    = sheets.aggregate(t=Sum('total_cash'))['t']              or Decimal('0')
        total_momo    = sheets.aggregate(t=Sum('total_momo'))['t']              or Decimal('0')
        total_pos     = sheets.aggregate(t=Sum('total_pos'))['t']               or Decimal('0')
        total_collected = total_cash + total_momo + total_pos
        total_petty   = sheets.aggregate(t=Sum('total_petty_cash_out'))['t']    or Decimal('0')
        total_credit_issued  = sheets.aggregate(t=Sum('total_credit_issued'))['t']  or Decimal('0')
        total_credit_settled = sheets.aggregate(t=Sum('total_credit_settled'))['t'] or Decimal('0')

        # ── Daily breakdown ───────────────────────────────────────────────
        daily_breakdown = [
            {
                'date'  : sheet.date.isoformat(),
                'day'   : sheet.date.strftime('%A'),
                'status': sheet.status,
                'cash'  : str(sheet.total_cash),
                'momo'  : str(sheet.total_momo),
                'pos'   : str(sheet.total_pos),
                'total' : str(sheet.total_cash + sheet.total_momo + sheet.total_pos),
                'jobs'  : sheet.total_jobs_created,
            }
            for sheet in sheets
        ]

        # ── Weekly breakdown ──────────────────────────────────────────────
        weekly_reports = WeeklyReport.objects.filter(
            branch         = self.branch,
            year           = self.year,
            date_from__gte = first_day,
            date_to__lte   = last_day,
        ).order_by('week_number')

        weekly_breakdown = [
            {
                'week_number': wr.week_number,
                'date_from'  : wr.date_from.isoformat(),
                'date_to'    : wr.date_to.isoformat(),
                'cash'       : str(wr.total_cash),
                'momo'       : str(wr.total_momo),
                'pos'        : str(wr.total_pos),
                'total'      : str(wr.total_collected),
                'jobs'       : wr.total_jobs_created,
                'status'     : wr.status,
            }
            for wr in weekly_reports
        ]

        # ── Jobs summary ──────────────────────────────────────────────────
        all_jobs = Job.objects.filter(
            branch                = self.branch,
            created_at__date__gte = first_day,
            created_at__date__lte = last_day,
        )
        job_totals = all_jobs.aggregate(
            total    = Count('id'),
            complete = Count('id', filter=Q(status=Job.COMPLETE)),
            cancelled= Count('id', filter=Q(status=Job.CANCELLED)),
            pending  = Count('id', filter=Q(status=Job.PENDING_PAYMENT)),
        )

        # ── Top services by revenue ───────────────────────────────────────
        top_by_revenue = JobLineItem.objects.filter(
            job__branch                = self.branch,
            job__status                = Job.COMPLETE,
            job__created_at__date__gte = first_day,
            job__created_at__date__lte = last_day,
        ).values('service__name').annotate(
            revenue  = Sum('line_total'),
            job_count= Count('job', distinct=True),
        ).order_by('-revenue')[:5]

        top_services = [
            {
                'service'  : r['service__name'],
                'revenue'  : str(r['revenue'] or 0),
                'job_count': r['job_count'],
            }
            for r in top_by_revenue
        ]

        # ── Staff performance ─────────────────────────────────────────────
        staff_performance = Job.objects.filter(
            branch                = self.branch,
            status                = Job.COMPLETE,
            created_at__date__gte = first_day,
            created_at__date__lte = last_day,
            intake_by__isnull     = False,
        ).values(
            'intake_by__first_name',
            'intake_by__last_name',
        ).annotate(
            jobs_recorded=Count('id'),
            revenue      =Sum('amount_paid'),
        ).order_by('-jobs_recorded')

        staff_stats = [
            {
                'intake_by__first_name': r['intake_by__first_name'],
                'intake_by__last_name' : r['intake_by__last_name'],
                'jobs_recorded'        : r['jobs_recorded'],
                'revenue'              : str(r['revenue'] or 0),
            }
            for r in staff_performance
        ]

        # ── Inventory summary ─────────────────────────────────────────────
        stock_in = StockMovement.objects.filter(
            branch                = self.branch,
            movement_type         = 'IN',
            created_at__date__gte = first_day,
            created_at__date__lte = last_day,
        ).aggregate(
            total_received=Sum('quantity'),
            movements     =Count('id'),
        )

        waste_total = WasteIncident.objects.filter(
            branch                = self.branch,
            created_at__date__gte = first_day,
            created_at__date__lte = last_day,
        ).aggregate(total_incidents=Count('id'))

        return {
            'branch'      : self.branch.name,
            'month'       : self.month,
            'year'        : self.year,
            'month_name'  : calendar.month_name[self.month],
            'first_day'   : first_day.isoformat(),
            'last_day'    : last_day.isoformat(),
            'generated_at': timezone.now().isoformat(),

            'revenue': {
                'total_collected'      : str(total_collected),
                'total_cash'           : str(total_cash),
                'total_momo'           : str(total_momo),
                'total_pos'            : str(total_pos),
                'total_petty_cash_out' : str(total_petty),
                'total_credit_issued'  : str(total_credit_issued),
                'total_credit_settled' : str(total_credit_settled),
                'cash_pct' : round(float(total_cash) / float(total_collected) * 100, 1) if total_collected else 0,
                'momo_pct' : round(float(total_momo) / float(total_collected) * 100, 1) if total_collected else 0,
                'pos_pct'  : round(float(total_pos)  / float(total_collected) * 100, 1) if total_collected else 0,
            },

            'jobs': {
                'total'          : job_totals['total']     or 0,
                'complete'       : job_totals['complete']  or 0,
                'cancelled'      : job_totals['cancelled'] or 0,
                'pending'        : job_totals['pending']   or 0,
                'completion_rate': round(
                    job_totals['complete'] / job_totals['total'] * 100, 1
                ) if job_totals['total'] else 0,
            },

            'top_services'     : top_services,
            'staff_performance': staff_stats,
            'daily_breakdown'  : daily_breakdown,
            'weekly_breakdown' : weekly_breakdown,

            'inventory': {
                'total_received' : str(stock_in['total_received'] or 0),
                'movements_in'   : stock_in['movements'] or 0,
                'waste_incidents': waste_total['total_incidents'] or 0,
            },
        }

    # ── Status transitions ────────────────────────────────────────────────

    @transaction.atomic
    def submit(self, bm_user, bm_notes: str = '') -> tuple:
        """BM submits the monthly close. Triggers Finance assignment."""
        from apps.finance.models import MonthlyClose

        integrity = self.check_integrity()
        if not integrity['can_submit']:
            errors = [c['detail'] for c in integrity['checks'].values() if not c['pass']]
            return None, errors

        close, _ = self.get_or_create()
        if not close.can_submit:
            return None, [f"Cannot submit — current status is {close.status}."]

        snapshot = self.build_snapshot()

        close.status           = MonthlyClose.Status.SUBMITTED
        close.submitted_by     = bm_user
        close.submitted_at     = timezone.now()
        close.bm_notes         = bm_notes
        close.summary_snapshot = snapshot
        close.rejection_reason = ''
        close.save()

        # Assign Finance reviewer immediately
        reviewer = self._assign_finance_reviewer(close)
        if reviewer:
            close.finance_reviewer   = reviewer
            close.finance_assigned_at = timezone.now()
            close.status             = MonthlyClose.Status.FINANCE_REVIEWING
            close.save(update_fields=['finance_reviewer', 'finance_assigned_at', 'status'])
            self._notify_finance_reviewer(close)

        # Assign Finance reviewer immediately
        reviewer = self._assign_finance_reviewer(close)
        if reviewer:
            close.finance_reviewer    = reviewer
            close.finance_assigned_at = timezone.now()
            close.status              = MonthlyClose.Status.FINANCE_REVIEWING
            close.save(update_fields=['finance_reviewer', 'finance_assigned_at', 'status'])
            self._notify_finance_reviewer(close)
            self._notify_bm_finance_assigned(close)
        else:
            logger.warning(
                'MonthlyCloseEngine: no Finance reviewer available for %s/%s — notifying RM',
                self.month, self.year,
            )
            self._notify_rm_submitted(close)

        logger.info(
            'MonthlyCloseEngine: %s submitted monthly close for %s/%s',
            bm_user.full_name, self.month, self.year,
        )

        return close, []

    @transaction.atomic
    def request_clarification(self, finance_user, clarification: str) -> tuple:
        """Finance flags items requiring BM clarification. BM has 24 hours."""
        from apps.finance.models import MonthlyClose

        if not clarification.strip():
            return None, ['Clarification request cannot be empty.']

        close, _ = self.get_or_create()
        if not close.can_request_clarification:
            return None, [f"Cannot request clarification — current status is {close.status}."]

        close.status                 = MonthlyClose.Status.NEEDS_CLARIFICATION
        close.clarification_request  = clarification
        close.clarification_due_at   = timezone.now() + timedelta(hours=24)
        close.clarification_response = ''
        close.save()

        self._notify_bm_clarification(close)

        logger.info(
            'MonthlyCloseEngine: %s requested clarification on %s/%s',
            finance_user.full_name, self.month, self.year,
        )

        return close, []

    @transaction.atomic
    def respond_clarification(self, bm_user, response: str) -> tuple:
        """BM responds to Finance clarification request."""
        from apps.finance.models import MonthlyClose

        if not response.strip():
            return None, ['Clarification response cannot be empty.']

        close, _ = self.get_or_create()
        if not close.can_respond_clarification:
            return None, [f"Cannot respond — current status is {close.status}."]

        close.status                 = MonthlyClose.Status.RESUBMITTED
        close.clarification_response = response
        close.save()

        self._notify_finance_reviewer_response(close)

        logger.info(
            'MonthlyCloseEngine: %s responded to clarification for %s/%s',
            bm_user.full_name, self.month, self.year,
        )

        return close, []

    @transaction.atomic
    def clear(self, finance_user, finance_notes: str = '') -> tuple:
        """Finance approves the close. RM can now endorse."""
        from apps.finance.models import MonthlyClose

        close, _ = self.get_or_create()
        if not close.can_clear:
            return None, [f"Cannot clear — current status is {close.status}."]

        close.status             = MonthlyClose.Status.FINANCE_CLEARED
        close.finance_cleared_at = timezone.now()
        close.finance_notes      = finance_notes
        close.save()

        self._notify_rm_cleared(close)

        logger.info(
            'MonthlyCloseEngine: %s cleared monthly close %s for %s/%s',
            finance_user.full_name, close.pk, self.month, self.year,
        )

        return close, []

    @transaction.atomic
    def endorse(self, rm_user, rm_notes: str = '') -> tuple:
        """RM endorses the monthly close after Finance has cleared."""
        from apps.finance.models import MonthlyClose

        close, _ = self.get_or_create()
        if not close.can_endorse:
            return None, [f"Cannot endorse — current status is {close.status}."]

        close.status      = MonthlyClose.Status.ENDORSED
        close.endorsed_by = rm_user
        close.endorsed_at = timezone.now()
        close.rm_notes    = rm_notes
        close.save()

        self._notify_bm_endorsed(close)

        logger.info(
            'MonthlyCloseEngine: %s endorsed monthly close %s for %s/%s',
            rm_user.full_name, close.pk, self.month, self.year,
        )

        return close, []

    @transaction.atomic
    def reject(self, rm_user, reason: str) -> tuple:
        """RM rejects the monthly close at any post-SUBMITTED stage."""
        from apps.finance.models import MonthlyClose

        if not reason.strip():
            return None, ['Rejection reason is required.']

        close, _ = self.get_or_create()
        if not close.can_reject:
            return None, [f"Cannot reject — current status is {close.status}."]

        close.status           = MonthlyClose.Status.REJECTED
        close.rejected_by      = rm_user
        close.rejected_at      = timezone.now()
        close.rejection_reason = reason
        close.save()

        self._notify_bm_rejected(close, reason)

        logger.info(
            'MonthlyCloseEngine: %s rejected monthly close %s — %s',
            rm_user.full_name, close.pk, reason,
        )

        return close, []

    @transaction.atomic
    def lock(self, downloaded_by, ip_address: str = '') -> tuple:
        """
        Lock the close permanently. Called on first PDF download after endorsement.
        Logs who downloaded, when, and from what IP.
        """
        from apps.finance.models import MonthlyClose

        close, _ = self.get_or_create()
        if not close.can_lock:
            return None, [f"Cannot lock — current status is {close.status}."]

        close.status             = MonthlyClose.Status.LOCKED
        close.locked_at          = timezone.now()
        close.pdf_downloaded_by  = downloaded_by
        close.pdf_downloaded_at  = timezone.now()
        close.save()

        logger.info(
            'MonthlyCloseEngine: monthly close %s LOCKED by %s from %s',
            close.pk, downloaded_by.full_name, ip_address or 'unknown',
        )

        return close, []

    # ── Notifications ─────────────────────────────────────────────────────

    def _notify_rm_submitted(self, close) -> None:
        """Fallback: notify RM when no Finance reviewer is configured."""
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            rm_users = CustomUser.objects.filter(
                role__name='REGIONAL_MANAGER',
                is_active=True,
            )
            for rm in rm_users:
                notify(
                    recipient=rm,
                    verb='MONTHLY_CLOSE_SUBMITTED',
                    message=(
                        f"{self.branch.name} submitted their "
                        f"{close.month_name} {self.year} monthly close. "
                        f"No Finance reviewer is configured — please assign one."
                    ),
                    link='/portal/regional-manager/',
                )
        except Exception:
            logger.exception('MonthlyCloseEngine: failed to notify RM of submission')

    def _notify_finance_reviewer(self, close) -> None:
        try:
            from apps.notifications.services import notify

            if close.finance_reviewer:
                notify(
                    recipient=close.finance_reviewer,
                    verb='MONTHLY_CLOSE_ASSIGNED',
                    message=(
                        f"{self.branch.name} — {close.month_name} {self.year} monthly close "
                        f"has been assigned to you for review."
                    ),
                    link='/portal/finance/',
                )
        except Exception:
            logger.exception('MonthlyCloseEngine: failed to notify Finance reviewer')

    def _notify_bm_clarification(self, close) -> None:
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            bm = CustomUser.objects.filter(
                branch    =self.branch,
                role__name='BRANCH_MANAGER',
                is_active =True,
            ).first()

            if bm:
                notify(
                    recipient=bm,
                    verb='MONTHLY_CLOSE_CLARIFICATION',
                    message=(
                        f"Finance has requested clarification on your "
                        f"{close.month_name} {self.year} monthly close. "
                        f"Please respond within 24 hours."
                    ),
                    link='/portal/dashboard/',
                )
        except Exception:
            logger.exception('MonthlyCloseEngine: failed to notify BM of clarification request')

    def _notify_finance_reviewer_response(self, close) -> None:
        try:
            from apps.notifications.services import notify

            if close.finance_reviewer:
                notify(
                    recipient=close.finance_reviewer,
                    verb='MONTHLY_CLOSE_RESUBMITTED',
                    message=(
                        f"{self.branch.name} has responded to your clarification request "
                        f"for the {close.month_name} {self.year} monthly close."
                    ),
                    link='/portal/finance/',
                )
        except Exception:
            logger.exception('MonthlyCloseEngine: failed to notify Finance reviewer of response')

    def _notify_rm_cleared(self, close) -> None:
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            rm_users = CustomUser.objects.filter(
                role__name='REGIONAL_MANAGER',
                is_active=True,
            )
            for rm in rm_users:
                notify(
                    recipient=rm,
                    verb='MONTHLY_CLOSE_FINANCE_CLEARED',
                    message=(
                        f"{self.branch.name} — {close.month_name} {self.year} monthly close "
                        f"has been cleared by Finance and is ready for your endorsement."
                    ),
                    link='/portal/regional-manager/',
                )
        except Exception:
            logger.exception('MonthlyCloseEngine: failed to notify RM of Finance clearance')

    def _notify_bm_endorsed(self, close) -> None:
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            bm = CustomUser.objects.filter(
                branch    =self.branch,
                role__name='BRANCH_MANAGER',
                is_active =True,
            ).first()

            if bm:
                notify(
                    recipient=bm,
                    verb='MONTHLY_CLOSE_ENDORSED',
                    message=(
                        f"Your {close.month_name} {self.year} monthly close "
                        f"has been endorsed by {close.endorsed_by.full_name}."
                    ),
                    link='/portal/dashboard/',
                )
        except Exception:
            logger.exception('MonthlyCloseEngine: failed to notify BM of endorsement')

    def _notify_bm_rejected(self, close, reason: str) -> None:
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            bm = CustomUser.objects.filter(
                branch    =self.branch,
                role__name='BRANCH_MANAGER',
                is_active =True,
            ).first()

            if bm:
                notify(
                    recipient=bm,
                    verb='MONTHLY_CLOSE_REJECTED',
                    message=(
                        f"Your {close.month_name} {self.year} monthly close "
                        f"was rejected by {close.rejected_by.full_name}. "
                        f"Reason: {reason}"
                    ),
                    link='/portal/dashboard/',
                )
        except Exception:
            logger.exception('MonthlyCloseEngine: failed to notify BM of rejection')

    # ── PDF generation ────────────────────────────────────────────────────

    def generate_pdf(self, close) -> bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, PageBreak,
        )
        from reportlab.lib.enums import TA_CENTER
        import io

        snap    = close.summary_snapshot
        revenue = snap.get('revenue', {})
        jobs    = snap.get('jobs', {})
        buf     = io.BytesIO()

        # ── Color palette ─────────────────────────────────────────────────
        BLACK      = colors.HexColor('#1a1a1a')
        DARK_GREY  = colors.HexColor('#374151')
        MID_GREY   = colors.HexColor('#6b7280')
        LIGHT_GREY = colors.HexColor('#f3f4f6')
        BORDER     = colors.HexColor('#e5e7eb')
        GREEN      = colors.HexColor('#166534')
        GREEN_BG   = colors.HexColor('#dcfce7')
        AMBER      = colors.HexColor('#92400e')
        AMBER_BG   = colors.HexColor('#fef3c7')
        RED        = colors.HexColor('#991b1b')
        RED_BG     = colors.HexColor('#fee2e2')
        BLUE       = colors.HexColor('#1e40af')
        BLUE_BG    = colors.HexColor('#dbeafe')
        PURPLE     = colors.HexColor('#6b21a8')
        PURPLE_BG  = colors.HexColor('#f3e8ff')

        status_map = {
            'OPEN'               : (BLUE,   BLUE_BG,   'OPEN'),
            'SUBMITTED'          : (AMBER,  AMBER_BG,  'SUBMITTED — AWAITING FINANCE REVIEW'),
            'FINANCE_REVIEWING'  : (BLUE,   BLUE_BG,   'FINANCE REVIEWING'),
            'NEEDS_CLARIFICATION': (AMBER,  AMBER_BG,  'NEEDS CLARIFICATION'),
            'RESUBMITTED'        : (PURPLE, PURPLE_BG, 'RESUBMITTED — FINANCE RE-REVIEWING'),
            'FINANCE_CLEARED'    : (GREEN,  GREEN_BG,  'FINANCE CLEARED — AWAITING RM ENDORSEMENT'),
            'ENDORSED'           : (GREEN,  GREEN_BG,  'ENDORSED BY REGIONAL MANAGER'),
            'LOCKED'             : (GREEN,  GREEN_BG,  'LOCKED & FINALISED'),
            'REJECTED'           : (RED,    RED_BG,    'REJECTED'),
        }
        s_color, s_bg, s_label = status_map.get(close.status, (MID_GREY, LIGHT_GREY, close.status))

        doc = SimpleDocTemplate(
            buf,
            pagesize    =A4,
            leftMargin  =20*mm,
            rightMargin =20*mm,
            topMargin   =20*mm,
            bottomMargin=20*mm,
            title       =f"Monthly Close — {snap.get('month_name')} {snap.get('year')}",
        )

        styles = getSampleStyleSheet()
        story  = []

        def h1(text):
            return Paragraph(text, ParagraphStyle(
                'H1', fontSize=20, fontName='Helvetica-Bold',
                textColor=BLACK, spaceAfter=4,
            ))

        def h2(text):
            return Paragraph(text, ParagraphStyle(
                'H2', fontSize=13, fontName='Helvetica-Bold',
                textColor=BLACK, spaceBefore=14, spaceAfter=6,
            ))

        def body(text, color=DARK_GREY, size=10):
            return Paragraph(text, ParagraphStyle(
                'Body', fontSize=size, fontName='Helvetica',
                textColor=color, spaceAfter=2,
            ))

        def divider():
            return HRFlowable(width='100%', thickness=0.5, color=BORDER, spaceAfter=10, spaceBefore=4)

        def fmt(val):
            try:
                return f"GHS {float(val):,.2f}"
            except Exception:
                return str(val)

        # ── Cover ─────────────────────────────────────────────────────────
        story.append(Spacer(1, 10*mm))
        story.append(h1('FARHAT PRINTING PRESS'))
        story.append(body(snap.get('branch', ''), size=12))
        story.append(Spacer(1, 6*mm))
        story.append(Paragraph(
            '<b>Monthly Close Report</b>',
            ParagraphStyle('MC', fontSize=16, fontName='Helvetica-Bold', textColor=BLACK, spaceAfter=4),
        ))
        story.append(body(f"{snap.get('month_name')} {snap.get('year')}", size=14))
        story.append(Spacer(1, 4*mm))

        status_table = Table(
            [[Paragraph(f"<b>{s_label}</b>",
               ParagraphStyle('ST', fontSize=10, fontName='Helvetica-Bold',
                              textColor=s_color, alignment=TA_CENTER))]],
            colWidths=[80*mm],
        )
        status_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), s_bg),
            ('TOPPADDING',    (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(status_table)
        story.append(Spacer(1, 6*mm))

        # Meta info
        meta_data = [
            ['Period',       f"{snap.get('first_day')} — {snap.get('last_day')}"],
            ['Branch',       snap.get('branch', '—')],
            ['Submitted By', close.submitted_by.full_name if close.submitted_by else '—'],
            ['Submitted At', close.submitted_at.strftime('%d %b %Y %H:%M') if close.submitted_at else '—'],
        ]
        if close.finance_reviewer:
            meta_data.append(['Finance Reviewer', close.finance_reviewer.full_name])
        if close.finance_cleared_at:
            meta_data.append(['Finance Cleared', close.finance_cleared_at.strftime('%d %b %Y %H:%M')])
        if close.endorsed_by:
            meta_data.append(['Endorsed By', close.endorsed_by.full_name])
            meta_data.append(['Endorsed At', close.endorsed_at.strftime('%d %b %Y %H:%M')])
        if close.locked_at:
            meta_data.append(['Locked At', close.locked_at.strftime('%d %b %Y %H:%M')])

        meta_table = Table(meta_data, colWidths=[45*mm, 110*mm])
        meta_table.setStyle(TableStyle([
            ('FONTNAME',      (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 9),
            ('TEXTCOLOR',     (0,0), (0,-1), MID_GREY),
            ('TEXTCOLOR',     (1,0), (1,-1), DARK_GREY),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LINEBELOW',     (0,0), (-1,-2), 0.3, BORDER),
        ]))
        story.append(meta_table)
        story.append(PageBreak())

        # ── Revenue summary ───────────────────────────────────────────────
        story.append(h2('Revenue Summary'))
        story.append(divider())

        rev_data = [
            ['', 'Amount', '% of Total'],
            ['Cash',           fmt(revenue.get('total_cash', 0)), f"{revenue.get('cash_pct', 0)}%"],
            ['Mobile Money',   fmt(revenue.get('total_momo', 0)), f"{revenue.get('momo_pct', 0)}%"],
            ['POS',            fmt(revenue.get('total_pos',  0)), f"{revenue.get('pos_pct',  0)}%"],
            ['TOTAL COLLECTED',fmt(revenue.get('total_collected', 0)), '100%'],
            ['Petty Cash Out', fmt(revenue.get('total_petty_cash_out', 0)), ''],
            ['Credit Issued',  fmt(revenue.get('total_credit_issued',  0)), ''],
            ['Credit Settled', fmt(revenue.get('total_credit_settled', 0)), ''],
        ]
        rev_table = Table(rev_data, colWidths=[80*mm, 55*mm, 30*mm])
        rev_table.setStyle(TableStyle([
            ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTNAME',      (0,4), (-1,4),  'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 9),
            ('BACKGROUND',    (0,0), (-1,0),  LIGHT_GREY),
            ('BACKGROUND',    (0,4), (-1,4),  GREEN_BG),
            ('TEXTCOLOR',     (0,4), (-1,4),  GREEN),
            ('ALIGN',         (1,0), (-1,-1), 'RIGHT'),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LINEBELOW',     (0,0), (-1,-2), 0.3, BORDER),
            ('LINEBELOW',     (0,3), (-1,3),  1.0, BORDER),
        ]))
        story.append(rev_table)
        story.append(Spacer(1, 8*mm))

        # ── Jobs summary ──────────────────────────────────────────────────
        story.append(h2('Jobs Summary'))
        story.append(divider())

        jobs_data = [
            ['Metric', 'Count'],
            ['Total Jobs Created', str(jobs.get('total',     0))],
            ['Completed',          str(jobs.get('complete',  0))],
            ['Cancelled',          str(jobs.get('cancelled', 0))],
            ['Pending Payment',    str(jobs.get('pending',   0))],
            ['Completion Rate',    f"{jobs.get('completion_rate', 0)}%"],
        ]
        jobs_table = Table(jobs_data, colWidths=[110*mm, 55*mm])
        jobs_table.setStyle(TableStyle([
            ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 9),
            ('BACKGROUND',    (0,0), (-1,0),  LIGHT_GREY),
            ('ALIGN',         (1,0), (-1,-1), 'RIGHT'),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LINEBELOW',     (0,0), (-1,-2), 0.3, BORDER),
        ]))
        story.append(jobs_table)
        story.append(Spacer(1, 8*mm))

        # ── Top services ──────────────────────────────────────────────────
        top_services = snap.get('top_services', [])
        if top_services:
            story.append(h2('Top Services by Revenue'))
            story.append(divider())
            svc_data = [['Service', 'Jobs', 'Revenue']]
            for svc in top_services:
                svc_data.append([svc['service'], str(svc['job_count']), fmt(svc['revenue'])])
            svc_table = Table(svc_data, colWidths=[90*mm, 30*mm, 45*mm])
            svc_table.setStyle(TableStyle([
                ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
                ('FONTSIZE',      (0,0), (-1,-1), 9),
                ('BACKGROUND',    (0,0), (-1,0),  LIGHT_GREY),
                ('ALIGN',         (1,0), (-1,-1), 'RIGHT'),
                ('TOPPADDING',    (0,0), (-1,-1), 5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
                ('LINEBELOW',     (0,0), (-1,-2), 0.3, BORDER),
            ]))
            story.append(svc_table)
            story.append(Spacer(1, 8*mm))

        # ── Staff performance ─────────────────────────────────────────────
        staff = snap.get('staff_performance', [])
        if staff:
            story.append(h2('Staff Performance'))
            story.append(divider())
            staff_data = [['Staff Member', 'Jobs Recorded', 'Revenue Generated']]
            for s in staff:
                name = f"{s.get('intake_by__first_name','')} {s.get('intake_by__last_name','')}".strip() or '—'
                staff_data.append([name, str(s['jobs_recorded']), fmt(s['revenue'])])
            staff_table = Table(staff_data, colWidths=[80*mm, 40*mm, 45*mm])
            staff_table.setStyle(TableStyle([
                ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
                ('FONTSIZE',      (0,0), (-1,-1), 9),
                ('BACKGROUND',    (0,0), (-1,0),  LIGHT_GREY),
                ('ALIGN',         (1,0), (-1,-1), 'RIGHT'),
                ('TOPPADDING',    (0,0), (-1,-1), 5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
                ('LINEBELOW',     (0,0), (-1,-2), 0.3, BORDER),
            ]))
            story.append(staff_table)
            story.append(Spacer(1, 8*mm))

        # ── Daily breakdown ───────────────────────────────────────────────
        story.append(PageBreak())
        story.append(h2('Daily Breakdown'))
        story.append(divider())

        daily = snap.get('daily_breakdown', [])
        if daily:
            daily_data = [['Date', 'Day', 'Cash', 'MoMo', 'POS', 'Total', 'Jobs']]
            for d in daily:
                daily_data.append([
                    d['date'], d['day'],
                    fmt(d['cash']), fmt(d['momo']), fmt(d['pos']),
                    fmt(d['total']), str(d['jobs']),
                ])
            daily_table = Table(daily_data, colWidths=[22*mm, 22*mm, 24*mm, 24*mm, 20*mm, 26*mm, 15*mm])
            daily_table.setStyle(TableStyle([
                ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
                ('FONTSIZE',      (0,0), (-1,-1), 8),
                ('BACKGROUND',    (0,0), (-1,0),  LIGHT_GREY),
                ('ALIGN',         (2,0), (-1,-1), 'RIGHT'),
                ('TOPPADDING',    (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('LINEBELOW',     (0,0), (-1,-2), 0.3, BORDER),
                ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, LIGHT_GREY]),
            ]))
            story.append(daily_table)

        # ── Weekly breakdown ──────────────────────────────────────────────
        story.append(Spacer(1, 8*mm))
        story.append(h2('Weekly Breakdown'))
        story.append(divider())

        weekly = snap.get('weekly_breakdown', [])
        if weekly:
            weekly_data = [['Week', 'Period', 'Cash', 'MoMo', 'Total', 'Jobs']]
            for w in weekly:
                weekly_data.append([
                    f"W{w['week_number']}",
                    f"{w['date_from']} – {w['date_to']}",
                    fmt(w['cash']), fmt(w['momo']), fmt(w['total']), str(w['jobs']),
                ])
            weekly_table = Table(weekly_data, colWidths=[15*mm, 45*mm, 28*mm, 28*mm, 28*mm, 15*mm])
            weekly_table.setStyle(TableStyle([
                ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
                ('FONTSIZE',      (0,0), (-1,-1), 8),
                ('BACKGROUND',    (0,0), (-1,0),  LIGHT_GREY),
                ('ALIGN',         (2,0), (-1,-1), 'RIGHT'),
                ('TOPPADDING',    (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('LINEBELOW',     (0,0), (-1,-2), 0.3, BORDER),
            ]))
            story.append(weekly_table)

        # ── Notes sections ────────────────────────────────────────────────
        if close.bm_notes:
            story.append(Spacer(1, 8*mm))
            story.append(h2('Branch Manager Notes'))
            story.append(divider())
            story.append(body(close.bm_notes))

        if close.clarification_request:
            story.append(Spacer(1, 6*mm))
            story.append(h2('Finance Clarification Request'))
            story.append(divider())
            story.append(body(close.clarification_request))

        if close.clarification_response:
            story.append(Spacer(1, 6*mm))
            story.append(h2('Branch Manager Clarification Response'))
            story.append(divider())
            story.append(body(close.clarification_response))

        if close.finance_notes:
            story.append(Spacer(1, 6*mm))
            story.append(h2('Finance Notes'))
            story.append(divider())
            story.append(body(close.finance_notes))

        if close.rm_notes:
            story.append(Spacer(1, 6*mm))
            story.append(h2('Regional Manager Notes'))
            story.append(divider())
            story.append(body(close.rm_notes))

        if close.rejection_reason:
            story.append(Spacer(1, 6*mm))
            story.append(h2('Rejection Reason'))
            story.append(divider())
            story.append(body(close.rejection_reason, color=RED))

        # ── Footer ────────────────────────────────────────────────────────
        story.append(Spacer(1, 10*mm))
        story.append(divider())
        story.append(body(
            f"Generated by Octos Operations Platform — {timezone.now().strftime('%d %b %Y %H:%M')}",
            color=MID_GREY, size=8,
        ))
        story.append(body(
            'Farhat Printing Press — CONFIDENTIAL — For Internal Use Only',
            color=MID_GREY, size=8,
        ))

        doc.build(story)
        buf.seek(0)
        return buf.read()