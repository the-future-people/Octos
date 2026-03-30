"""
MonthlyCloseEngine
==================
Handles all business logic for the End-of-Month Close process.

Responsibilities:
  - Integrity checks before BM can submit
  - Building the full month summary snapshot
  - PDF generation (ReportLab)
  - Status transitions (submit, endorse, reject)
"""

import logging
import calendar
from datetime import date
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
        """Get or create the MonthlyClose record for this branch/month/year."""
        from apps.finance.models import MonthlyClose
        close, created = MonthlyClose.objects.get_or_create(
            branch = self.branch,
            month  = self.month,
            year   = self.year,
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
        today     = timezone.localdate()

        checks = {}

        # 1. Today must be the last day of the month
        checks['last_day_of_month'] = {
            'pass'   : today >= last_day,
            'label'  : 'Last day of month',
            'detail' : f"Today is {today}. Month ends {last_day}.",
        }

        # 2. All daily sheets for the month must be closed
        open_sheets = DailySalesSheet.objects.filter(
            branch     = self.branch,
            date__gte  = first_day,
            date__lte  = last_day,
            status     = DailySalesSheet.Status.OPEN,
        )
        open_count = open_sheets.count()
        checks['all_sheets_closed'] = {
            'pass'   : open_count == 0,
            'label'  : 'All daily sheets closed',
            'detail' : f"{open_count} sheet(s) still open." if open_count else "All sheets closed.",
        }

        # 3. All weekly filings for the month must be submitted/locked
        from apps.finance.models import WeeklyReport
        draft_reports = WeeklyReport.objects.filter(
            branch    = self.branch,
            year      = self.year,
            status    = WeeklyReport.Status.DRAFT,
            date_from__gte = first_day,
            date_to__lte   = last_day,
        )
        draft_count = draft_reports.count()
        checks['all_weekly_filed'] = {
            'pass'   : draft_count == 0,
            'label'  : 'All weekly filings submitted',
            'detail' : f"{draft_count} weekly filing(s) still in draft." if draft_count else "All weekly filings submitted.",
        }

        # 4. No pending payment jobs from this month
        pending_jobs = Job.objects.filter(
            branch           = self.branch,
            status           = Job.PENDING_PAYMENT,
            created_at__date__gte = first_day,
            created_at__date__lte = last_day,
        )
        pending_count = pending_jobs.count()
        checks['no_pending_payments'] = {
            'pass'   : pending_count == 0,
            'label'  : 'No pending payments',
            'detail' : f"{pending_count} job(s) still pending payment." if pending_count else "No pending payments.",
        }

        # 5. No unsigned cashier floats from this month
        unsigned_floats = CashierFloat.objects.filter(
            daily_sheet__branch    = self.branch,
            daily_sheet__date__gte = first_day,
            daily_sheet__date__lte = last_day,
            is_signed_off          = False,
        )
        unsigned_count = unsigned_floats.count()
        checks['no_unsigned_floats'] = {
            'pass'   : unsigned_count == 0,
            'label'  : 'All cashier floats signed off',
            'detail' : f"{unsigned_count} float(s) not signed off." if unsigned_count else "All floats signed off.",
        }

        can_submit = all(c['pass'] for c in checks.values())

        return {
            'can_submit' : can_submit,
            'checks'     : checks,
            'month'      : self.month,
            'year'       : self.year,
            'last_day'   : last_day.isoformat(),
        }

    # ── Snapshot ──────────────────────────────────────────────────────────

    def build_snapshot(self) -> dict:
        """
        Build the full month summary snapshot.
        Called at submit time — frozen forever after.
        """
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

        jobs = Job.objects.filter(
            branch           = self.branch,
            status           = Job.COMPLETE,
            created_at__date__gte = first_day,
            created_at__date__lte = last_day,
        )

        # ── Revenue totals ────────────────────────────────────────────────
        total_cash = sheets.aggregate(t=Sum('total_cash'))['t'] or Decimal('0')
        total_momo = sheets.aggregate(t=Sum('total_momo'))['t'] or Decimal('0')
        total_pos  = sheets.aggregate(t=Sum('total_pos'))['t']  or Decimal('0')
        total_collected = total_cash + total_momo + total_pos
        total_petty = sheets.aggregate(t=Sum('total_petty_cash_out'))['t'] or Decimal('0')
        total_credit_issued   = sheets.aggregate(t=Sum('total_credit_issued'))['t']   or Decimal('0')
        total_credit_settled  = sheets.aggregate(t=Sum('total_credit_settled'))['t']  or Decimal('0')

        # ── Daily breakdown ───────────────────────────────────────────────
        daily_breakdown = []
        for sheet in sheets:
            daily_breakdown.append({
                'date'       : sheet.date.isoformat(),
                'day'        : sheet.date.strftime('%A'),
                'status'     : sheet.status,
                'cash'       : str(sheet.total_cash),
                'momo'       : str(sheet.total_momo),
                'pos'        : str(sheet.total_pos),
                'total'      : str(sheet.total_cash + sheet.total_momo + sheet.total_pos),
                'jobs'       : sheet.total_jobs_created,
            })

        # ── Weekly breakdown ──────────────────────────────────────────────
        weekly_reports = WeeklyReport.objects.filter(
            branch         = self.branch,
            year           = self.year,
            date_from__gte = first_day,
            date_to__lte   = last_day,
        ).order_by('week_number')

        weekly_breakdown = []
        for wr in weekly_reports:
            weekly_breakdown.append({
                'week_number' : wr.week_number,
                'date_from'   : wr.date_from.isoformat(),
                'date_to'     : wr.date_to.isoformat(),
                'cash'        : str(wr.total_cash),
                'momo'        : str(wr.total_momo),
                'pos'         : str(wr.total_pos),
                'total'       : str(wr.total_collected),
                'jobs'        : wr.total_jobs_created,
                'status'      : wr.status,
            })

        # ── Jobs summary ──────────────────────────────────────────────────
        all_jobs = Job.objects.filter(
            branch           = self.branch,
            created_at__date__gte = first_day,
            created_at__date__lte = last_day,
        )
        job_totals = all_jobs.aggregate(
            total     = Count('id'),
            complete  = Count('id', filter=Q(status=Job.COMPLETE)),
            cancelled = Count('id', filter=Q(status=Job.CANCELLED)),
            pending   = Count('id', filter=Q(status=Job.PENDING_PAYMENT)),
        )

        # ── Top services by revenue ───────────────────────────────────────
        top_by_revenue = JobLineItem.objects.filter(
            job__branch           = self.branch,
            job__status           = Job.COMPLETE,
            job__created_at__date__gte = first_day,
            job__created_at__date__lte = last_day,
        ).values('service__name').annotate(
            revenue   = Sum('line_total'),
            job_count = Count('job', distinct=True),
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
            branch           = self.branch,
            status           = Job.COMPLETE,
            created_at__date__gte = first_day,
            created_at__date__lte = last_day,
            intake_by__isnull     = False,
        ).values(
            'intake_by__full_name'
        ).annotate(
            jobs_recorded = Count('id'),
            revenue       = Sum('amount_paid'),
        ).order_by('-jobs_recorded')

        staff_stats = [
            {
                'name'         : r['intake_by__full_name'],
                'jobs_recorded': r['jobs_recorded'],
                'revenue'      : str(r['revenue'] or 0),
            }
            for r in staff_performance
        ]

        # ── Inventory summary ─────────────────────────────────────────────
        stock_in = StockMovement.objects.filter(
            branch           = self.branch,
            movement_type    = 'IN',
            created_at__date__gte = first_day,
            created_at__date__lte = last_day,
        ).aggregate(
            total_received = Sum('quantity'),
            movements      = Count('id'),
        )

        waste_total = WasteIncident.objects.filter(
            branch           = self.branch,
            created_at__date__gte = first_day,
            created_at__date__lte = last_day,
        ).aggregate(
            total_incidents = Count('id'),
        )

        return {
            'branch'     : self.branch.name,
            'month'      : self.month,
            'year'       : self.year,
            'month_name' : calendar.month_name[self.month],
            'first_day'  : first_day.isoformat(),
            'last_day'   : last_day.isoformat(),
            'generated_at': timezone.now().isoformat(),

            'revenue': {
                'total_collected'      : str(total_collected),
                'total_cash'           : str(total_cash),
                'total_momo'           : str(total_momo),
                'total_pos'            : str(total_pos),
                'total_petty_cash_out' : str(total_petty),
                'total_credit_issued'  : str(total_credit_issued),
                'total_credit_settled' : str(total_credit_settled),
                'cash_pct'  : round(float(total_cash)  / float(total_collected) * 100, 1) if total_collected else 0,
                'momo_pct'  : round(float(total_momo)  / float(total_collected) * 100, 1) if total_collected else 0,
                'pos_pct'   : round(float(total_pos)   / float(total_collected) * 100, 1) if total_collected else 0,
            },

            'jobs': {
                'total'    : job_totals['total']     or 0,
                'complete' : job_totals['complete']  or 0,
                'cancelled': job_totals['cancelled'] or 0,
                'pending'  : job_totals['pending']   or 0,
                'completion_rate': round(
                    job_totals['complete'] / job_totals['total'] * 100, 1
                ) if job_totals['total'] else 0,
            },

            'top_services'     : top_services,
            'staff_performance': staff_stats,
            'daily_breakdown'  : daily_breakdown,
            'weekly_breakdown' : weekly_breakdown,

            'inventory': {
                'total_received'  : str(stock_in['total_received'] or 0),
                'movements_in'    : stock_in['movements'] or 0,
                'waste_incidents' : waste_total['total_incidents'] or 0,
            },
        }

    # ── Status transitions ────────────────────────────────────────────────

    @transaction.atomic
    def submit(self, bm_user, bm_notes: str = '') -> tuple:
        """
        BM submits the monthly close.
        Returns (MonthlyClose, errors list).
        """
        from apps.finance.models import MonthlyClose

        integrity = self.check_integrity()
        if not integrity['can_submit']:
            errors = [
                c['detail'] for c in integrity['checks'].values()
                if not c['pass']
            ]
            return None, errors

        close, _ = self.get_or_create()

        if not close.can_submit:
            return None, [f"Cannot submit — current status is {close.status}."]

        snapshot = self.build_snapshot()

        close.status          = MonthlyClose.Status.SUBMITTED
        close.submitted_by    = bm_user
        close.submitted_at    = timezone.now()
        close.bm_notes        = bm_notes
        close.summary_snapshot = snapshot
        close.rejection_reason = ''
        close.save()

        self._notify_belt_manager(close)

        logger.info(
            'MonthlyCloseEngine: %s submitted monthly close for %s/%s',
            bm_user.full_name, self.month, self.year,
        )

        return close, []

    @transaction.atomic
    def endorse(self, belt_user, belt_notes: str = '') -> tuple:
        """Belt Manager endorses the monthly close."""
        from apps.finance.models import MonthlyClose

        close, _ = self.get_or_create()
        if not close.can_endorse:
            return None, [f"Cannot endorse — current status is {close.status}."]

        close.status      = MonthlyClose.Status.ENDORSED
        close.endorsed_by = belt_user
        close.endorsed_at = timezone.now()
        close.belt_notes  = belt_notes
        close.save()

        self._notify_bm_endorsed(close)

        logger.info(
            'MonthlyCloseEngine: %s endorsed monthly close %s for %s/%s',
            belt_user.full_name, close.pk, self.month, self.year,
        )

        return close, []

    @transaction.atomic
    def reject(self, belt_user, reason: str) -> tuple:
        """Belt Manager rejects the monthly close with a reason."""
        from apps.finance.models import MonthlyClose

        if not reason.strip():
            return None, ['Rejection reason is required.']

        close, _ = self.get_or_create()
        if not close.can_reject:
            return None, [f"Cannot reject — current status is {close.status}."]

        close.status           = MonthlyClose.Status.REJECTED
        close.rejected_by      = belt_user
        close.rejected_at      = timezone.now()
        close.rejection_reason = reason
        close.save()

        self._notify_bm_rejected(close, reason)

        logger.info(
            'MonthlyCloseEngine: %s rejected monthly close %s — %s',
            belt_user.full_name, close.pk, reason,
        )

        return close, []

    # ── Notifications ─────────────────────────────────────────────────────

    def _notify_belt_manager(self, close) -> None:
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            belt_managers = CustomUser.objects.filter(
                role__name = 'BELT_MANAGER',
                is_active  = True,
            )
            for bm in belt_managers:
                notify(
                    recipient = bm,
                    verb      = 'MONTHLY_CLOSE_SUBMITTED',
                    message   = (
                        f"{self.branch.name} has submitted their "
                        f"{close.month_name} {self.year} monthly close "
                        f"for your endorsement."
                    ),
                    link = '/portal/belt-manager/',
                )
        except Exception:
            logger.exception('MonthlyCloseEngine: failed to notify belt manager')

    def _notify_bm_endorsed(self, close) -> None:
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            bm = CustomUser.objects.filter(
                branch    = self.branch,
                role__name= 'BRANCH_MANAGER',
                is_active = True,
            ).first()

            if bm:
                notify(
                    recipient = bm,
                    verb      = 'MONTHLY_CLOSE_ENDORSED',
                    message   = (
                        f"Your {close.month_name} {self.year} monthly close "
                        f"has been endorsed and finalized by "
                        f"{close.endorsed_by.full_name}."
                    ),
                    link = '/portal/dashboard/',
                )
        except Exception:
            logger.exception('MonthlyCloseEngine: failed to notify BM of endorsement')

    def _notify_bm_rejected(self, close, reason: str) -> None:
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            bm = CustomUser.objects.filter(
                branch    = self.branch,
                role__name= 'BRANCH_MANAGER',
                is_active = True,
            ).first()

            if bm:
                notify(
                    recipient = bm,
                    verb      = 'MONTHLY_CLOSE_REJECTED',
                    message   = (
                        f"Your {close.month_name} {self.year} monthly close "
                        f"was rejected by {close.rejected_by.full_name}. "
                        f"Reason: {reason}"
                    ),
                    link = '/portal/dashboard/',
                )
        except Exception:
            logger.exception('MonthlyCloseEngine: failed to notify BM of rejection')

    # ── PDF generation ────────────────────────────────────────────────────

    def generate_pdf(self, close) -> bytes:
        """
        Generate the monthly close PDF using ReportLab.
        Returns raw PDF bytes.
        """
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, PageBreak,
        )
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
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

        # Status colour
        status_map = {
            'SUBMITTED': (AMBER,    AMBER_BG,  'AWAITING ENDORSEMENT'),
            'ENDORSED' : (GREEN,    GREEN_BG,  'ENDORSED & FINALIZED'),
            'REJECTED' : (RED,      RED_BG,    'REJECTED'),
            'OPEN'     : (BLUE,     BLUE_BG,   'OPEN'),
        }
        s_color, s_bg, s_label = status_map.get(close.status, (MID_GREY, LIGHT_GREY, close.status))

        doc = SimpleDocTemplate(
            buf,
            pagesize     = A4,
            leftMargin   = 20*mm,
            rightMargin  = 20*mm,
            topMargin    = 20*mm,
            bottomMargin = 20*mm,
            title        = f"Monthly Close — {snap.get('month_name')} {snap.get('year')}",
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
            f"<b>Monthly Close Report</b>",
            ParagraphStyle('MC', fontSize=16, fontName='Helvetica-Bold',
                           textColor=BLACK, spaceAfter=4)
        ))
        story.append(body(f"{snap.get('month_name')} {snap.get('year')}", size=14))
        story.append(Spacer(1, 4*mm))

        # Status badge
        status_table = Table(
            [[Paragraph(f"<b>{s_label}</b>",
               ParagraphStyle('ST', fontSize=10, fontName='Helvetica-Bold',
                              textColor=s_color, alignment=TA_CENTER))]],
            colWidths=[60*mm],
        )
        status_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), s_bg),
            ('ROUNDEDCORNERS', [4]),
            ('TOPPADDING',    (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(status_table)
        story.append(Spacer(1, 6*mm))

        # Meta info
        meta_data = [
            ['Period', f"{snap.get('first_day')} — {snap.get('last_day')}"],
            ['Branch', snap.get('branch', '—')],
            ['Submitted By', close.submitted_by.full_name if close.submitted_by else '—'],
            ['Submitted At', close.submitted_at.strftime('%d %b %Y %H:%M') if close.submitted_at else '—'],
        ]
        if close.endorsed_by:
            meta_data.append(['Endorsed By', close.endorsed_by.full_name])
            meta_data.append(['Endorsed At', close.endorsed_at.strftime('%d %b %Y %H:%M')])

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
            ['Cash',         fmt(revenue.get('total_cash', 0)),  f"{revenue.get('cash_pct', 0)}%"],
            ['Mobile Money', fmt(revenue.get('total_momo', 0)),  f"{revenue.get('momo_pct', 0)}%"],
            ['POS',          fmt(revenue.get('total_pos',  0)),  f"{revenue.get('pos_pct',  0)}%"],
            ['TOTAL COLLECTED', fmt(revenue.get('total_collected', 0)), '100%'],
            ['Petty Cash Out',  fmt(revenue.get('total_petty_cash_out', 0)), ''],
            ['Credit Issued',   fmt(revenue.get('total_credit_issued',  0)), ''],
            ['Credit Settled',  fmt(revenue.get('total_credit_settled', 0)), ''],
        ]
        rev_table = Table(rev_data, colWidths=[80*mm, 55*mm, 30*mm])
        rev_table.setStyle(TableStyle([
            ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTNAME',      (0,4), (-1,4),  'Helvetica-Bold'),
            ('FONTNAME',      (0,1), (0,-1),  'Helvetica'),
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
            ['Total Jobs Created',  str(jobs.get('total',     0))],
            ['Completed',           str(jobs.get('complete',  0))],
            ['Cancelled',           str(jobs.get('cancelled', 0))],
            ['Pending Payment',     str(jobs.get('pending',   0))],
            ['Completion Rate',     f"{jobs.get('completion_rate', 0)}%"],
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
                svc_data.append([
                    svc['service'],
                    str(svc['job_count']),
                    fmt(svc['revenue']),
                ])
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
                staff_data.append([s['name'], str(s['jobs_recorded']), fmt(s['revenue'])])
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
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, LIGHT_GREY]),
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
                    fmt(w['cash']), fmt(w['momo']),
                    fmt(w['total']), str(w['jobs']),
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

        # ── BM notes ──────────────────────────────────────────────────────
        if close.bm_notes:
            story.append(Spacer(1, 8*mm))
            story.append(h2('Branch Manager Notes'))
            story.append(divider())
            story.append(body(close.bm_notes))

        # ── Belt Manager notes ────────────────────────────────────────────
        if close.belt_notes:
            story.append(Spacer(1, 6*mm))
            story.append(h2('Belt Manager Notes'))
            story.append(divider())
            story.append(body(close.belt_notes))

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