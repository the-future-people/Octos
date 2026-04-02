"""
MonthlyEngine — compiles MonthlyCloseSummary from all risk intelligence.

Called by: analytics.tasks.monthly.compile_monthly_summary (Celery task)
Triggered by: MonthlyClose status → SUBMITTED signal

Reads from:
  - DailyRiskReport / DailyRiskFlag (daily risk data)
  - WeeklyRiskScore / WeeklyRiskFlag (weekly risk data)
  - UserSession (session intelligence)
  - MonthlyClose.summary_snapshot (BM-submitted financials)

Produces:
  - One MonthlyCloseSummary per MonthlyClose
  - Assigns Finance reviewer using round-robin
  - Notifies Finance reviewer
"""

import logging
from django.utils import timezone

logger = logging.getLogger(__name__)

# Finance review threshold — all monthly closes go to Finance
# but we flag the risk level prominently
FINANCE_REVIEW_THRESHOLD = 0  # All closes require Finance review


class MonthlyEngine:

    def __init__(self, monthly_close):
        self.close  = monthly_close
        self.branch = monthly_close.branch
        self.month  = monthly_close.month
        self.year   = monthly_close.year

    def compile(self):
        """
        Compile MonthlyCloseSummary from all available risk intelligence.
        Returns the MonthlyCloseSummary instance.
        """
        from apps.analytics.models import (
            MonthlyCloseSummary,
            DailyRiskReport,
            WeeklyRiskScore,
            UserSession,
        )
        from apps.finance.models import DailySalesSheet, WeeklyReport

        logger.info(
            'MonthlyEngine.compile: close=%s branch=%s %s/%s',
            self.close.pk, self.branch.code, self.month, self.year,
        )

        # ── Gather daily sheets for this month ────────────────
        daily_sheets = DailySalesSheet.objects.filter(
            branch     = self.branch,
            date__year = self.year,
            date__month= self.month,
        )

        # ── Gather daily risk reports ─────────────────────────
        daily_reports = DailyRiskReport.objects.filter(
            daily_sheet__in = daily_sheets,
        ).prefetch_related('flags')

        # ── Gather weekly risk scores ─────────────────────────
        weekly_reports = WeeklyReport.objects.filter(
            branch = self.branch,
            year   = self.year,
        ).filter(
            # Weeks that overlap with this month
            date_from__month__lte = self.month,
            date_to__month__gte   = self.month,
        )
        weekly_scores = WeeklyRiskScore.objects.filter(
            weekly_report__in = weekly_reports,
        ).prefetch_related('flags')

        # ── Gather session data ───────────────────────────────
        sessions = UserSession.objects.filter(
            branch             = self.branch,
            started_at__year   = self.year,
            started_at__month  = self.month,
        )

        # ── Compile risk metrics ──────────────────────────────
        daily_scores      = [r.risk_score for r in daily_reports]
        overall_risk      = int(sum(daily_scores) / len(daily_scores)) if daily_scores else 0
        critical_days     = sum(1 for s in daily_scores if s >= 70)
        high_risk_days    = sum(1 for s in daily_scores if 40 <= s < 70)
        weeks_flagged     = weekly_scores.filter(finance_status='FLAGGED').count()

        # ── Session metrics ───────────────────────────────────
        total_sessions       = sessions.count()
        anomalous_sessions   = sessions.filter(is_anomalous=True).count()
        critical_switches    = sum(
            s.critical_action_switches for s in sessions
        )

        # ── Compile all flags into one list ───────────────────
        all_flags = []

        for report in daily_reports:
            for flag in report.flags.all():
                all_flags.append({
                    'source'     : 'DAILY',
                    'date'       : str(report.date),
                    'type'       : flag.flag_type,
                    'severity'   : flag.severity,
                    'description': flag.description,
                    'metadata'   : flag.metadata,
                })

        for score in weekly_scores:
            for flag in score.flags.all():
                all_flags.append({
                    'source'     : 'WEEKLY',
                    'week'       : score.week_number,
                    'type'       : flag.flag_type,
                    'severity'   : flag.severity,
                    'description': flag.description,
                    'metadata'   : flag.metadata,
                })

        # Sort by severity for Finance reading order
        severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
        all_flags.sort(key=lambda f: severity_order.get(f['severity'], 4))

        # ── Create or update MonthlyCloseSummary ──────────────
        summary, created = MonthlyCloseSummary.objects.get_or_create(
            monthly_close = self.close,
            defaults      = {
                'branch'      : self.branch,
                'month'       : self.month,
                'year'        : self.year,
                'generated_at': timezone.now(),
            }
        )

        summary.overall_risk_score      = overall_risk
        summary.critical_days_count     = critical_days
        summary.high_risk_days_count    = high_risk_days
        summary.weeks_flagged_count     = weeks_flagged
        summary.total_sessions          = total_sessions
        summary.anomalous_sessions_count = anomalous_sessions
        summary.total_critical_switches = critical_switches
        summary.all_flags               = all_flags
        summary.generated_at            = timezone.now()
        summary.save()

        # ── Assign Finance reviewer ───────────────────────────
        if not summary.finance_reviewer:
            self._assign_finance_reviewer(summary)

        logger.info(
            'MonthlyEngine: close=%s risk=%s flags=%s critical_days=%s',
            self.close.pk, overall_risk, len(all_flags), critical_days,
        )

        return summary

    def _assign_finance_reviewer(self, summary):
        """
        Assign Finance reviewer using round-robin across active Finance users.
        Every monthly close goes to Finance — no threshold here.
        """
        try:
            from apps.accounts.models import CustomUser
            from apps.analytics.models import MonthlyCloseSummary
            from apps.notifications.models import Notification

            finance_users = CustomUser.objects.filter(
                role__name = 'FINANCE',
                is_active  = True,
            ).order_by('id')

            if not finance_users.exists():
                logger.warning(
                    'MonthlyEngine: no active Finance users found. '
                    'Create Finance users before monthly closes can be reviewed.'
                )
                return

            # Round-robin: assign to Finance user with fewest pending reviews
            assignment_counts = {
                u.pk: MonthlyCloseSummary.objects.filter(
                    finance_reviewer = u,
                    finance_status   = 'PENDING',
                ).count()
                for u in finance_users
            }

            assigned = min(finance_users, key=lambda u: assignment_counts[u.pk])

            summary.finance_reviewer    = assigned
            summary.finance_assigned_at = timezone.now()
            summary.save(update_fields=['finance_reviewer', 'finance_assigned_at'])

            # Notify Finance reviewer
            import calendar
            month_name = calendar.month_name[self.month]

            Notification.objects.create(
                recipient = assigned,
                message   = (
                    f"Monthly close assigned for Finance review: "
                    f"{self.branch.name} — {month_name} {self.year}. "
                    f"Overall risk score: {summary.overall_risk_score}/100. "
                    f"Total flags: {len(summary.all_flags)}."
                ),
                verb = 'FINANCE_REVIEW_ASSIGNED',
            )

            # Also notify RM that Finance review is pending
            self._notify_rm_finance_pending(summary, month_name)

            logger.info(
                'MonthlyEngine: assigned to Finance user %s',
                assigned.full_name
            )

        except Exception as e:
            logger.error('_assign_finance_reviewer failed: %s', e, exc_info=True)

    def _notify_rm_finance_pending(self, summary, month_name):
        """Notify RM that Finance review is in progress."""
        try:
            from apps.accounts.models import CustomUser
            from apps.notifications.models import Notification

            region = getattr(self.branch, 'region', None)
            if not region:
                return

            rm_users = CustomUser.objects.filter(
                region     = region,
                role__name = 'REGIONAL_MANAGER',
                is_active  = True,
            )

            for rm in rm_users:
                Notification.objects.create(
                    recipient = rm,
                    message   = (
                        f"{self.branch.name} — {month_name} {self.year} monthly close "
                        f"submitted and assigned to Finance for review. "
                        f"You will be notified when Finance clears it for endorsement."
                    ),
                    verb = 'MONTHLY_FINANCE_PENDING',
                )

        except Exception as e:
            logger.error('_notify_rm_finance_pending failed: %s', e, exc_info=True)