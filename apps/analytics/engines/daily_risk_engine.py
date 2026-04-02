"""
DailyRiskEngine — analyses a closed DailySalesSheet for risk signals.

Called by: analytics.tasks.daily.analyse_daily_risk (Celery task)
Triggered by: on_sheet_saved signal when sheet status → CLOSED

Produces:
  - One DailyRiskReport per sheet
  - One DailyRiskFlag per detected anomaly

Design rules:
  - Engine never modifies operational data
  - All checks are independent — one failing check never blocks others
  - Descriptions are human-readable and self-contained
  - Thresholds are constants at the top — easy to tune
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Thresholds (tune these as you learn the branch patterns) ──────────────────
CASH_VARIANCE_MEDIUM_GHS    = 10     # GHS 10+ variance → MEDIUM
CASH_VARIANCE_HIGH_GHS      = 50     # GHS 50+ variance → HIGH
CASH_VARIANCE_CRITICAL_GHS  = 200    # GHS 200+ variance → CRITICAL

HIGH_SINGLE_PAYMENT_GHS     = 500    # Single payment > GHS 500 → LOW flag
HIGH_SINGLE_PAYMENT_CRIT    = 2000   # Single payment > GHS 2000 → HIGH flag

PAYMENT_METHOD_SHIFT_PCT    = 30     # If cash% shifts by 30+ points vs 30-day avg → MEDIUM
PAYMENT_METHOD_CASH_MAX_PCT = 90     # If cash > 90% of total → LOW (hard to verify)

SHORT_SESSION_MINUTES       = 60     # Session < 60min on a full day → LOW
CARRY_FORWARD_HIGH_COUNT    = 5      # > 5 pending payment jobs at close → MEDIUM


class DailyRiskEngine:

    def __init__(self, sheet):
        self.sheet  = sheet
        self.branch = sheet.branch
        self.date   = sheet.date
        self.flags  = []  # List of (flag_type, severity, description, metadata)

    def analyse(self):
        """
        Run all checks and produce a DailyRiskReport.
        Returns the DailyRiskReport instance.
        """
        from apps.analytics.models import DailyRiskReport, DailyRiskFlag

        logger.info(
            'DailyRiskEngine.analyse: sheet=%s branch=%s date=%s',
            self.sheet.pk, self.branch.code, self.date
        )

        # ── Run all checks ────────────────────────────────────
        self._check_float_variance()
        self._check_float_not_acknowledged()
        self._check_float_not_signed_off()
        self._check_post_closing_jobs()
        self._check_carry_forward()
        self._check_high_single_payments()
        self._check_duplicate_amounts()
        self._check_payment_method_distribution()
        self._check_sessions()

        # ── Create report ─────────────────────────────────────
        report, created = DailyRiskReport.objects.get_or_create(
            daily_sheet = self.sheet,
            defaults    = {
                'branch'      : self.branch,
                'date'        : self.date,
                'generated_at': timezone.now(),
            }
        )

        if not created:
            # Re-analysis — clear existing flags
            report.flags.all().delete()
            report.generated_at = timezone.now()
            report.save(update_fields=['generated_at'])

        # ── Write flags ───────────────────────────────────────
        for flag_type, severity, description, metadata in self.flags:
            DailyRiskFlag.objects.create(
                report      = report,
                flag_type   = flag_type,
                severity    = severity,
                description = description,
                metadata    = metadata,
            )

        # ── Compute score ─────────────────────────────────────
        report.compute_score()

        logger.info(
            'DailyRiskEngine: sheet=%s risk_score=%s flags=%s',
            self.sheet.pk, report.risk_score, report.total_flags
        )

        # ── Route alerts ──────────────────────────────────────
        self._route_alerts(report)

        return report

    # ── Check: Float variance ─────────────────────────────────────────────────

    def _check_float_variance(self):
        """
        Cash variance at float sign-off.
        Expected = opening float + cash collected - petty cash out.
        """
        from apps.finance.models import CashierFloat

        floats = CashierFloat.objects.filter(
            daily_sheet = self.sheet,
            is_signed_off = True,
        )

        for f in floats:
            variance = abs(float(f.variance or 0))
            if variance < 0.01:
                continue

            if variance >= CASH_VARIANCE_CRITICAL_GHS:
                severity = 'CRITICAL'
            elif variance >= CASH_VARIANCE_HIGH_GHS:
                severity = 'HIGH'
            elif variance >= CASH_VARIANCE_MEDIUM_GHS:
                severity = 'MEDIUM'
            else:
                severity = 'LOW'

            direction = 'surplus' if float(f.variance or 0) > 0 else 'shortage'

            self.flags.append((
                'CASH_VARIANCE',
                severity,
                (
                    f"Cash {direction} of GHS {variance:.2f} detected for "
                    f"{f.cashier.full_name}. "
                    f"Expected GHS {float(f.expected_cash):.2f}, "
                    f"counted GHS {float(f.closing_cash):.2f}. "
                    f"Notes: {f.variance_notes or 'None provided.'}"
                ),
                {
                    'cashier_id'   : f.cashier.pk,
                    'cashier_name' : f.cashier.full_name,
                    'opening_float': float(f.opening_float),
                    'closing_cash' : float(f.closing_cash),
                    'expected_cash': float(f.expected_cash),
                    'variance'     : float(f.variance),
                    'direction'    : direction,
                },
            ))

    # ── Check: Float not acknowledged ─────────────────────────────────────────

    def _check_float_not_acknowledged(self):
        """Float set but cashier never acknowledged receipt."""
        from apps.finance.models import CashierFloat

        unacknowledged = CashierFloat.objects.filter(
            daily_sheet          = self.sheet,
            morning_acknowledged = False,
        )

        for f in unacknowledged:
            self.flags.append((
                'FLOAT_NOT_ACKNOWLEDGED',
                'HIGH',
                (
                    f"Float of GHS {float(f.opening_float):.2f} was set for "
                    f"{f.cashier.full_name} but was never acknowledged. "
                    f"This means the cashier may have started collecting "
                    f"payments without confirming receipt of their float."
                ),
                {
                    'cashier_id'   : f.cashier.pk,
                    'cashier_name' : f.cashier.full_name,
                    'opening_float': float(f.opening_float),
                },
            ))

    # ── Check: Float not signed off ───────────────────────────────────────────

    def _check_float_not_signed_off(self):
        """Float acknowledged but cashier never signed off at EOD."""
        from apps.finance.models import CashierFloat

        unsigned = CashierFloat.objects.filter(
            daily_sheet          = self.sheet,
            morning_acknowledged = True,
            is_signed_off        = False,
        )

        for f in unsigned:
            self.flags.append((
                'FLOAT_NOT_SIGNED_OFF',
                'HIGH',
                (
                    f"{f.cashier.full_name} acknowledged their float but "
                    f"did not complete EOD sign-off. "
                    f"Closing cash count and variance are not recorded."
                ),
                {
                    'cashier_id'   : f.cashier.pk,
                    'cashier_name' : f.cashier.full_name,
                    'opening_float': float(f.opening_float),
                },
            ))

    # ── Check: Post-closing jobs ───────────────────────────────────────────────

    def _check_post_closing_jobs(self):
        """Jobs created after sheet was supposed to close."""
        from apps.jobs.models import Job

        post_closing = Job.objects.filter(
            daily_sheet  = self.sheet,
            post_closing = True,
        )

        count = post_closing.count()
        if not count:
            return

        severity = 'HIGH' if count > 3 else 'MEDIUM'

        jobs_detail = list(post_closing.values(
            'job_number', 'post_closing_reason',
            'intake_by__first_name', 'intake_by__last_name',
        ))

        self.flags.append((
            'POST_CLOSING_JOB',
            severity,
            (
                f"{count} job{'s' if count > 1 else ''} created after sheet close. "
                f"Post-closing jobs require BM approval and are a fraud risk "
                f"if not properly documented."
            ),
            {
                'count': count,
                'jobs' : [
                    {
                        'job_number': j['job_number'],
                        'reason'    : j['post_closing_reason'],
                        'intake_by' : f"{j['intake_by__first_name']} {j['intake_by__last_name']}".strip(),
                    }
                    for j in jobs_detail
                ],
            },
        ))

    # ── Check: Carry-forward ──────────────────────────────────────────────────

    def _check_carry_forward(self):
        """Jobs still pending payment at sheet close."""
        from apps.jobs.models import Job

        pending = Job.objects.filter(
            daily_sheet = self.sheet,
            status      = 'PENDING_PAYMENT',
        )
        count = pending.count()

        if count == 0:
            return

        severity = 'MEDIUM' if count >= CARRY_FORWARD_HIGH_COUNT else 'LOW'

        self.flags.append((
            'CARRY_FORWARD_HIGH',
            severity,
            (
                f"{count} job{'s' if count > 1 else ''} carried forward "
                f"with outstanding payment. "
                f"{'High carry-forward may indicate collection issues.' if count >= CARRY_FORWARD_HIGH_COUNT else 'Monitor for trend.'}"
            ),
            {
                'count': count,
                'job_numbers': list(pending.values_list('job_number', flat=True)),
            },
        ))

    # ── Check: High single payments ────────────────────────────────────────────

    def _check_high_single_payments(self):
        """Single payments significantly above normal."""
        from apps.finance.models import Receipt

        receipts = Receipt.objects.filter(
            daily_sheet = self.sheet,
            is_void     = False,
        )

        for r in receipts:
            amount = float(r.amount_paid or 0)

            if amount >= HIGH_SINGLE_PAYMENT_CRIT:
                severity = 'HIGH'
            elif amount >= HIGH_SINGLE_PAYMENT_GHS:
                severity = 'LOW'
            else:
                continue

            self.flags.append((
                'HIGH_SINGLE_PAYMENT',
                severity,
                (
                    f"Single payment of GHS {amount:.2f} detected "
                    f"(Receipt {r.receipt_number}, "
                    f"Method: {r.payment_method}). "
                    f"Verify this transaction is legitimate."
                ),
                {
                    'receipt_number': r.receipt_number,
                    'amount'        : amount,
                    'method'        : r.payment_method,
                    'cashier'       : r.cashier.full_name if r.cashier else '—',
                    'job_number'    : r.job.job_number if r.job else '—',
                },
            ))

    # ── Check: Duplicate amounts ──────────────────────────────────────────────

    def _check_duplicate_amounts(self):
        """Same amount confirmed multiple times in quick succession."""
        from apps.finance.models import Receipt
        from collections import defaultdict

        receipts = Receipt.objects.filter(
            daily_sheet = self.sheet,
            is_void     = False,
        ).order_by('created_at').values(
            'receipt_number', 'amount_paid', 'payment_method',
            'created_at', 'cashier__first_name', 'cashier__last_name',
        )

        # Group by (cashier, amount, method) — look for duplicates within 5 minutes
        seen = defaultdict(list)
        for r in receipts:
            key = (
                f"{r['cashier__first_name']} {r['cashier__last_name']}",
                str(r['amount_paid']),
                r['payment_method'],
            )
            seen[key].append(r)

        for (cashier, amount, method), group in seen.items():
            if len(group) < 2:
                continue

            # Check if any two receipts are within 5 minutes of each other
            for i in range(len(group) - 1):
                gap = (group[i+1]['created_at'] - group[i]['created_at']).total_seconds()
                if gap <= 300:  # 5 minutes
                    self.flags.append((
                        'DUPLICATE_AMOUNT',
                        'MEDIUM',
                        (
                            f"Duplicate payment of GHS {amount} via {method} "
                            f"confirmed {len(group)} times within 5 minutes "
                            f"by {cashier}. "
                            f"Verify these are distinct transactions."
                        ),
                        {
                            'cashier'       : cashier,
                            'amount'        : amount,
                            'method'        : method,
                            'count'         : len(group),
                            'receipt_numbers': [r['receipt_number'] for r in group],
                        },
                    ))
                    break

    # ── Check: Payment method distribution ────────────────────────────────────

    def _check_payment_method_distribution(self):
        """
        Unusual shift in payment method mix.
        Compares today's cash% against 30-day rolling average.
        Also flags if cash > 90% (hard to verify independently).
        """
        from apps.finance.models import Receipt
        from django.db.models import Sum

        receipts = Receipt.objects.filter(
            daily_sheet = self.sheet,
            is_void     = False,
        )
        total = float(receipts.aggregate(t=Sum('amount_paid'))['t'] or 0)
        if total == 0:
            return

        cash = float(receipts.filter(payment_method='CASH').aggregate(
            t=Sum('amount_paid'))['t'] or 0)
        cash_pct = (cash / total * 100) if total > 0 else 0

        # Hard check: cash > 90%
        if cash_pct >= PAYMENT_METHOD_CASH_MAX_PCT:
            self.flags.append((
                'PAYMENT_METHOD_SHIFT',
                'LOW',
                (
                    f"Cash payments represent {cash_pct:.1f}% of today's revenue "
                    f"(GHS {cash:.2f} of GHS {total:.2f}). "
                    f"High cash proportion is harder to independently verify."
                ),
                {
                    'cash_pct' : cash_pct,
                    'cash'     : cash,
                    'total'    : total,
                    'threshold': PAYMENT_METHOD_CASH_MAX_PCT,
                },
            ))
            return

        # Rolling average check: compare to last 30 days
        thirty_days_ago = self.date - timedelta(days=30)
        from apps.finance.models import DailySalesSheet
        historical = DailySalesSheet.objects.filter(
            branch   = self.branch,
            date__gte = thirty_days_ago,
            date__lt  = self.date,
            status__in = ['CLOSED', 'AUTO_CLOSED'],
        )

        if historical.count() < 5:
            return  # Not enough history to compare

        hist_total = float(historical.aggregate(t=Sum('total_cash') + Sum('total_momo') + Sum('total_pos'))['t'] or 0)
        hist_cash  = float(historical.aggregate(t=Sum('total_cash'))['t'] or 0)
        hist_pct   = (hist_cash / hist_total * 100) if hist_total > 0 else 0

        shift = abs(cash_pct - hist_pct)
        if shift >= PAYMENT_METHOD_SHIFT_PCT:
            direction = 'higher' if cash_pct > hist_pct else 'lower'
            self.flags.append((
                'PAYMENT_METHOD_SHIFT',
                'MEDIUM',
                (
                    f"Cash proportion today ({cash_pct:.1f}%) is {shift:.1f} percentage "
                    f"points {direction} than the 30-day average ({hist_pct:.1f}%). "
                    f"Unusual shifts in payment mix may warrant investigation."
                ),
                {
                    'today_cash_pct'  : cash_pct,
                    'avg_cash_pct'    : hist_pct,
                    'shift_pct'       : shift,
                    'direction'       : direction,
                    'historical_days' : historical.count(),
                },
            ))

    # ── Check: Session anomalies ──────────────────────────────────────────────

    def _check_sessions(self):
        """
        Check for unusual session patterns for this branch today.
        - Very short sessions on a busy day
        - High critical-action switches
        """
        from apps.analytics.models import UserSession
        from apps.jobs.models import Job

        sessions = UserSession.objects.filter(
            branch     = self.branch,
            started_at__date = self.date,
        )

        job_count = Job.objects.filter(daily_sheet=self.sheet).count()

        for s in sessions:
            # Short session on a busy day
            if (
                s.total_duration_seconds < SHORT_SESSION_MINUTES * 60
                and job_count > 10
                and s.ended_at is not None
            ):
                self.flags.append((
                    'SHORT_SESSION',
                    'LOW',
                    (
                        f"{s.user.full_name} ({s.portal}) had a session of only "
                        f"{s.duration_minutes:.0f} minutes on a day with "
                        f"{job_count} jobs recorded."
                    ),
                    {
                        'user_id'         : s.user.pk,
                        'user_name'       : s.user.full_name,
                        'portal'          : s.portal,
                        'duration_minutes': s.duration_minutes,
                        'job_count'       : job_count,
                    },
                ))

            # High critical-action switches
            if s.critical_action_switches >= 3:
                self.flags.append((
                    'CRITICAL_ACTION_SWITCH',
                    'MEDIUM',
                    (
                        f"{s.user.full_name} ({s.portal}) switched tabs or apps "
                        f"{s.critical_action_switches} times during critical actions "
                        f"(payment confirmation or EOD sign-off)."
                    ),
                    {
                        'user_id'         : s.user.pk,
                        'user_name'       : s.user.full_name,
                        'portal'          : s.portal,
                        'switch_count'    : s.critical_action_switches,
                    },
                ))

    # ── Alert routing ─────────────────────────────────────────────────────────

    def _route_alerts(self, report):
        """
        Route alerts to appropriate parties based on risk level.
        CRITICAL/HIGH → RM notification
        MEDIUM/LOW    → logged only, surfaced in weekly/monthly review
        """
        if not report.requires_rm_review:
            return

        try:
            from apps.notifications.models import Notification
            from apps.accounts.models import CustomUser

            # Find the RM for this branch's region
            branch  = self.branch
            region  = getattr(branch, 'region', None)
            if not region:
                return

            rm_users = CustomUser.objects.filter(
                region = region,
                role__name = 'REGIONAL_MANAGER',
                is_active  = True,
            )

            critical_count = report.flag_count_critical
            high_count     = report.flag_count_high

            if critical_count > 0:
                message = (
                    f"CRITICAL: {branch.name} — {self.date} has "
                    f"{critical_count} critical risk flag{'s' if critical_count > 1 else ''}. "
                    f"Immediate review required. Risk score: {report.risk_score}/100."
                )
            else:
                message = (
                    f"{branch.name} — {self.date} requires review. "
                    f"{high_count} high-risk flag{'s' if high_count > 1 else ''} detected. "
                    f"Risk score: {report.risk_score}/100."
                )

            for rm in rm_users:
                Notification.objects.create(
                    recipient = rm,
                    message   = message,
                    verb      = 'RISK_ALERT',
                )

        except Exception as e:
            logger.error('_route_alerts failed: %s', e, exc_info=True)