"""
WeeklyRiskEngine — analyses a WeeklyReport for risk signals.

Called by: analytics.tasks.weekly.compute_weekly_risk (Celery task)
Triggered by: WeeklyReport status → LOCKED signal (Session 3 wiring)

Produces:
  - One WeeklyRiskScore per WeeklyReport
  - One WeeklyRiskFlag per detected anomaly

Score algorithm:
  - Base: weighted average of daily risk scores for the week
    (CRITICAL days weighted 3x, HIGH days 2x, others 1x)
  - Plus: penalty points from week-level flags
  - Capped at 100

Finance spot-check threshold: score >= 50 or any CRITICAL flag.
"""

import logging
import statistics
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
CASH_PROPORTION_MAX_PCT     = 80    # Cash > 80% of weekly revenue → LOW flag
COMPLETION_RATE_DROP_PCT    = 15    # Completion rate drops > 15 points vs avg → MEDIUM
REVENUE_VS_PRIOR_DROP_PCT   = 30    # Revenue drops > 30% vs same week last month → MEDIUM
DAILY_OUTLIER_STD_DEVS      = 3     # Day > 3 std devs from week mean → HIGH
CARRY_FORWARD_HIGH_COUNT    = 10    # > 10 carry-forward jobs → MEDIUM
MULTIPLE_HIGH_RISK_DAYS     = 3     # >= 3 HIGH+ risk days in one week → HIGH
FINANCE_REVIEW_THRESHOLD    = 50    # Score >= 50 → requires Finance spot-check


class WeeklyRiskEngine:

    def __init__(self, weekly_report):
        self.report = weekly_report
        self.branch = weekly_report.branch
        self.flags  = []  # (flag_type, severity, description, metadata)

    def analyse(self):
        """
        Run all checks and produce a WeeklyRiskScore.
        Returns the WeeklyRiskScore instance.
        """
        from apps.analytics.models import WeeklyRiskScore, WeeklyRiskFlag, DailyRiskReport

        logger.info(
            'WeeklyRiskEngine.analyse: report=%s branch=%s W%s/%s',
            self.report.pk, self.branch.code,
            self.report.week_number, self.report.year,
        )

        # ── Gather daily risk data ────────────────────────────
        daily_sheets   = self.report.daily_sheets.all()
        daily_reports  = DailyRiskReport.objects.filter(
            daily_sheet__in = daily_sheets,
        ).order_by('date')

        daily_scores = [r.risk_score for r in daily_reports]

        # ── Run week-level checks ─────────────────────────────
        self._check_cash_proportion()
        self._check_completion_rate(daily_sheets)
        self._check_revenue_vs_prior()
        self._check_daily_outlier(daily_reports, daily_scores)
        self._check_carry_forward()
        self._check_multiple_high_risk_days(daily_reports)
        self._check_session_patterns()

        # ── Compute base score from daily risk scores ─────────
        base_score = self._compute_base_score(daily_reports, daily_scores)

        # ── Create or update WeeklyRiskScore ──────────────────
        score_record, created = WeeklyRiskScore.objects.get_or_create(
            weekly_report = self.report,
            defaults      = {
                'branch'      : self.branch,
                'week_number' : self.report.week_number,
                'year'        : self.report.year,
                'generated_at': timezone.now(),
            }
        )

        if not created:
            score_record.flags.all().delete()
            score_record.generated_at = timezone.now()
            score_record.save(update_fields=['generated_at'])

        # ── Write flags ───────────────────────────────────────
        for flag_type, severity, description, metadata in self.flags:
            WeeklyRiskFlag.objects.create(
                report      = score_record,
                flag_type   = flag_type,
                severity    = severity,
                description = description,
                metadata    = metadata,
            )

        # ── Compute final score ───────────────────────────────
        flag_penalty = self._compute_flag_penalty()
        final_score  = min(base_score + flag_penalty, 100)

        # ── Update score record ───────────────────────────────
        score_record.risk_score          = final_score
        score_record.highest_daily_risk  = max(daily_scores) if daily_scores else 0
        score_record.average_daily_risk  = int(statistics.mean(daily_scores)) if daily_scores else 0
        score_record.critical_days_count = sum(1 for s in daily_scores if s >= 70)
        score_record.high_days_count     = sum(1 for s in daily_scores if 40 <= s < 70)
        score_record.requires_finance_review = (
            final_score >= FINANCE_REVIEW_THRESHOLD or
            score_record.critical_days_count > 0
        )
        score_record.save(update_fields=[
            'risk_score',
            'highest_daily_risk',
            'average_daily_risk',
            'critical_days_count',
            'high_days_count',
            'requires_finance_review',
        ])

        # ── Assign Finance reviewer if needed ─────────────────
        if score_record.requires_finance_review and not score_record.finance_reviewer:
            self._assign_finance_reviewer(score_record)

        logger.info(
            'WeeklyRiskEngine: report=%s score=%s flags=%s requires_finance=%s',
            self.report.pk, final_score,
            len(self.flags), score_record.requires_finance_review,
        )

        return score_record

    # ── Base score computation ────────────────────────────────────────────────

    def _compute_base_score(self, daily_reports, daily_scores):
        """
        Weighted average of daily risk scores.
        CRITICAL days (score >= 70) weighted 3x.
        HIGH days (score >= 40) weighted 2x.
        Others weighted 1x.
        """
        if not daily_scores:
            return 0

        total_weight = 0
        weighted_sum = 0

        for report in daily_reports:
            score = report.risk_score
            if score >= 70:
                weight = 3
            elif score >= 40:
                weight = 2
            else:
                weight = 1
            weighted_sum  += score * weight
            total_weight  += weight

        if total_weight == 0:
            return 0

        return min(int(weighted_sum / total_weight), 100)

    def _compute_flag_penalty(self):
        """
        Additional penalty points from week-level flags.
        CRITICAL=20, HIGH=10, MEDIUM=5, LOW=2
        """
        weights = {'CRITICAL': 20, 'HIGH': 10, 'MEDIUM': 5, 'LOW': 2}
        return sum(weights.get(sev, 0) for _, sev, _, _ in self.flags)

    # ── Check: Cash proportion ────────────────────────────────────────────────

    def _check_cash_proportion(self):
        """Cash > 80% of weekly revenue is hard to independently verify."""
        total = float(self.report.total_collected or 0)
        cash  = float(self.report.total_cash or 0)

        if total == 0:
            return

        cash_pct = (cash / total) * 100
        if cash_pct < CASH_PROPORTION_MAX_PCT:
            return

        self.flags.append((
            'HIGH_CASH_PROPORTION',
            'LOW',
            (
                f"Cash payments represent {cash_pct:.1f}% of weekly revenue "
                f"(GHS {cash:.2f} of GHS {total:.2f} total). "
                f"Cash-heavy weeks are harder to independently reconcile."
            ),
            {
                'cash_pct' : cash_pct,
                'cash'     : cash,
                'total'    : total,
                'threshold': CASH_PROPORTION_MAX_PCT,
            },
        ))

    # ── Check: Completion rate vs branch average ──────────────────────────────

    def _check_completion_rate(self, daily_sheets):
        """Completion rate drops significantly vs 8-week rolling average."""
        from apps.jobs.models import Job

        total_jobs = Job.objects.filter(daily_sheet__in=daily_sheets).count()
        if total_jobs == 0:
            return

        completed    = Job.objects.filter(daily_sheet__in=daily_sheets, status='COMPLETE').count()
        current_rate = (completed / total_jobs) * 100

        # 8-week rolling average
        eight_weeks_ago = self.report.date_from - timedelta(weeks=8)
        from apps.finance.models import DailySalesSheet
        historical_sheets = DailySalesSheet.objects.filter(
            branch     = self.branch,
            date__gte  = eight_weeks_ago,
            date__lt   = self.report.date_from,
            status__in = ['CLOSED', 'AUTO_CLOSED'],
        )

        hist_total     = Job.objects.filter(daily_sheet__in=historical_sheets).count()
        hist_completed = Job.objects.filter(
            daily_sheet__in=historical_sheets, status='COMPLETE'
        ).count()

        if hist_total < 20:
            return  # Not enough history

        hist_rate = (hist_completed / hist_total) * 100
        drop      = hist_rate - current_rate

        if drop < COMPLETION_RATE_DROP_PCT:
            return

        self.flags.append((
            'COMPLETION_RATE_DROP',
            'MEDIUM',
            (
                f"Completion rate this week ({current_rate:.1f}%) is "
                f"{drop:.1f} percentage points below the 8-week average "
                f"({hist_rate:.1f}%). "
                f"Unusual drop may indicate operational issues or data quality problems."
            ),
            {
                'current_rate' : current_rate,
                'historical_rate': hist_rate,
                'drop'         : drop,
                'total_jobs'   : total_jobs,
                'completed'    : completed,
            },
        ))

    # ── Check: Revenue vs same week prior month ───────────────────────────────

    def _check_revenue_vs_prior(self):
        """Revenue drops > 30% vs same week number last month."""
        from apps.finance.models import WeeklyReport as WR

        current_total = float(self.report.total_collected or 0)
        if current_total == 0:
            return

        # Find same week number last year's month — use year-1 or same year, month-1
        prior_year = self.report.year if self.report.week_number > 4 else self.report.year - 1
        try:
            prior = WR.objects.filter(
                branch      = self.branch,
                week_number = self.report.week_number,
                year        = prior_year - 1 if self.report.year == prior_year else prior_year,
                status      = 'LOCKED',
            ).exclude(pk=self.report.pk).order_by('-year').first()

            if not prior:
                # Try week_number ± 1 from 4 weeks ago
                four_weeks_ago = self.report.week_number - 4
                if four_weeks_ago < 1:
                    return
                prior = WR.objects.filter(
                    branch      = self.branch,
                    week_number = four_weeks_ago,
                    year        = self.report.year,
                    status      = 'LOCKED',
                ).first()

            if not prior:
                return

            prior_total = float(prior.total_collected or 0)
            if prior_total == 0:
                return

            drop_pct = ((prior_total - current_total) / prior_total) * 100

            if drop_pct < REVENUE_VS_PRIOR_DROP_PCT:
                return

            self.flags.append((
                'REVENUE_VS_PRIOR',
                'MEDIUM',
                (
                    f"Revenue this week (GHS {current_total:.2f}) is "
                    f"{drop_pct:.1f}% lower than Week {prior.week_number} "
                    f"(GHS {prior_total:.2f}). "
                    f"Significant revenue drops warrant investigation."
                ),
                {
                    'current_total' : current_total,
                    'prior_total'   : prior_total,
                    'prior_week'    : prior.week_number,
                    'drop_pct'      : drop_pct,
                },
            ))
        except Exception as e:
            logger.warning('_check_revenue_vs_prior failed: %s', e)

    # ── Check: Daily outlier ──────────────────────────────────────────────────

    def _check_daily_outlier(self, daily_reports, daily_scores):
        """Single day > 3 standard deviations from week mean."""
        if len(daily_scores) < 3:
            return

        mean   = statistics.mean(daily_scores)
        stdev  = statistics.stdev(daily_scores)

        if stdev == 0:
            return

        for report in daily_reports:
            z_score = abs(report.risk_score - mean) / stdev
            if z_score >= DAILY_OUTLIER_STD_DEVS and report.risk_score > 0:
                self.flags.append((
                    'DAILY_OUTLIER',
                    'HIGH',
                    (
                        f"{report.date} had a risk score of {report.risk_score} "
                        f"({z_score:.1f} standard deviations above the week average of "
                        f"{mean:.1f}). This day is a significant outlier and requires review."
                    ),
                    {
                        'date'       : str(report.date),
                        'risk_score' : report.risk_score,
                        'week_mean'  : mean,
                        'z_score'    : z_score,
                        'flag_count' : report.total_flags,
                    },
                ))

    # ── Check: Carry-forward ──────────────────────────────────────────────────

    def _check_carry_forward(self):
        """High carry-forward count at week end."""
        count = int(self.report.carry_forward_count or 0)

        if count < CARRY_FORWARD_HIGH_COUNT:
            return

        self.flags.append((
            'CARRY_FORWARD_HIGH',
            'MEDIUM',
            (
                f"{count} jobs carried forward with outstanding payment at week end. "
                f"High carry-forward may indicate collection process issues "
                f"or cashier capacity problems."
            ),
            {
                'carry_forward_count': count,
                'threshold'          : CARRY_FORWARD_HIGH_COUNT,
            },
        ))

    # ── Check: Multiple high-risk days ────────────────────────────────────────

    def _check_multiple_high_risk_days(self, daily_reports):
        """3 or more HIGH+ risk days in a single week is a pattern."""
        high_days = [r for r in daily_reports if r.risk_score >= 40]
        count     = len(high_days)

        if count < MULTIPLE_HIGH_RISK_DAYS:
            return

        critical_count = sum(1 for r in high_days if r.risk_score >= 70)
        severity       = 'CRITICAL' if critical_count >= 2 else 'HIGH'

        self.flags.append((
            'MULTIPLE_HIGH_RISK',
            severity,
            (
                f"{count} days this week scored HIGH or above on risk assessment. "
                f"{'Including ' + str(critical_count) + ' CRITICAL day(s). ' if critical_count else ''}"
                f"Recurring risk across multiple days suggests a systemic issue."
            ),
            {
                'high_day_count'    : count,
                'critical_day_count': critical_count,
                'dates'             : [str(r.date) for r in high_days],
                'scores'            : [r.risk_score for r in high_days],
            },
        ))

    # ── Check: Session patterns ───────────────────────────────────────────────

    def _check_session_patterns(self):
        """Anomalous sessions detected across the week."""
        from apps.analytics.models import UserSession

        anomalous = UserSession.objects.filter(
            branch           = self.branch,
            started_at__date__gte = self.report.date_from,
            started_at__date__lte = self.report.date_to,
            is_anomalous          = True,
        ).count()

        total = UserSession.objects.filter(
            branch           = self.branch,
            started_at__date__gte = self.report.date_from,
            started_at__date__lte = self.report.date_to,
        ).count()

        if total == 0 or anomalous == 0:
            return

        anomaly_pct = (anomalous / total) * 100
        if anomaly_pct < 30:
            return

        self.flags.append((
            'SESSION_PATTERN',
            'MEDIUM',
            (
                f"{anomalous} of {total} sessions ({anomaly_pct:.0f}%) "
                f"this week were flagged as anomalous. "
                f"Unusual session patterns may indicate distraction, "
                f"process violations, or unauthorised access."
            ),
            {
                'anomalous_count': anomalous,
                'total_count'    : total,
                'anomaly_pct'    : anomaly_pct,
            },
        ))

    # ── Finance reviewer assignment ───────────────────────────────────────────

    def _assign_finance_reviewer(self, score_record):
        """
        Assign a Finance reviewer using round-robin across active Finance users.
        Finance users have no branch — they are HQ level.
        """
        try:
            from apps.accounts.models import CustomUser

            finance_users = CustomUser.objects.filter(
                role__name = 'FINANCE',
                is_active  = True,
            ).order_by('id')

            if not finance_users.exists():
                logger.warning('No active Finance users found for assignment.')
                return

            # Round-robin: find the Finance user with fewest recent assignments
            from apps.analytics.models import WeeklyRiskScore as WRS
            from django.db.models import Count

            assignment_counts = {
                u.pk: WRS.objects.filter(
                    finance_reviewer = u,
                    finance_status   = 'PENDING',
                ).count()
                for u in finance_users
            }

            assigned_user = min(finance_users, key=lambda u: assignment_counts[u.pk])

            score_record.finance_reviewer    = assigned_user
            score_record.finance_assigned_at = timezone.now()
            score_record.save(update_fields=['finance_reviewer', 'finance_assigned_at'])

            # Notify Finance reviewer
            from apps.notifications.models import Notification
            Notification.objects.create(
                recipient = assigned_user,
                message   = (
                    f"Weekly report assigned for Finance review: "
                    f"{self.branch.name} — Week {self.report.week_number}/{self.report.year}. "
                    f"Risk score: {score_record.risk_score}/100."
                ),
                verb = 'FINANCE_REVIEW_ASSIGNED',
            )

            logger.info(
                'WeeklyRiskEngine: assigned to Finance user %s',
                assigned_user.full_name
            )

        except Exception as e:
            logger.error('_assign_finance_reviewer failed: %s', e, exc_info=True)