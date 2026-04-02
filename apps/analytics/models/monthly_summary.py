from django.db import models


class MonthlyCloseSummary(models.Model):
    """
    Analytics intelligence layer for a monthly close.

    This model is the bridge between analytics and finance.
    It compiles all risk intelligence from the month — daily risk
    reports, weekly risk scores, session anomalies — into one place
    that Finance reads during their review.

    Relationship to MonthlyClose:
    - MonthlyClose (in finance app) owns the workflow:
      who submitted, who endorsed, what status, PDF
    - MonthlyCloseSummary (here) owns the intelligence:
      risk scores, flags, Finance reconciliation, clarifications

    The Finance review workflow lives here, not in MonthlyClose.
    RM can only endorse after finance_status = CLEARED.

    Clarification flow:
    1. Finance raises a question on a specific section
    2. clarification_requests entry created with asked_at
    3. BM sees it in their dashboard, responds
    4. Entry updated with response and responded_at
    5. Finance reviews response and either clears or raises another
    """

    monthly_close = models.OneToOneField(
        'finance.MonthlyClose',
        on_delete    = models.CASCADE,
        related_name = 'analytics_summary',
    )
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete    = models.CASCADE,
        related_name = 'monthly_summaries',
    )
    month = models.PositiveSmallIntegerField()
    year  = models.PositiveSmallIntegerField()

    # ── Compiled risk intelligence ────────────────────────────
    overall_risk_score   = models.PositiveSmallIntegerField(
        default   = 0,
        help_text = 'Weighted average of all weekly risk scores for the month.',
    )
    critical_days_count  = models.PositiveSmallIntegerField(
        default   = 0,
        help_text = 'Days where DailyRiskReport.risk_level = CRITICAL',
    )
    high_risk_days_count = models.PositiveSmallIntegerField(
        default   = 0,
        help_text = 'Days where DailyRiskReport.risk_level = HIGH',
    )
    weeks_flagged_count  = models.PositiveSmallIntegerField(
        default   = 0,
        help_text = 'Weeks where WeeklyRiskScore.finance_status = FLAGGED',
    )

    # ── Session intelligence ──────────────────────────────────
    total_sessions           = models.PositiveSmallIntegerField(default=0)
    anomalous_sessions_count = models.PositiveSmallIntegerField(default=0)
    total_critical_switches  = models.PositiveSmallIntegerField(
        default   = 0,
        help_text = 'Total TAB_SWITCH_CRITICAL events across all sessions this month',
    )

    # ── Compiled flags ────────────────────────────────────────
    all_flags = models.JSONField(
        default   = list,
        help_text = (
            'Flattened list of all DailyRiskFlags and WeeklyRiskFlags for the month. '
            'Finance reads this — one place to see every anomaly detected. '
            'Structure: [{type, severity, description, date, source}, ...]'
        ),
    )

    # ── Finance review ────────────────────────────────────────
    finance_reviewer = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.SET_NULL,
        null         = True,
        blank        = True,
        related_name = 'monthly_finance_reviews',
        help_text    = 'Assigned Finance reviewer. Set on submission.',
    )
    finance_assigned_at = models.DateTimeField(null=True, blank=True)
    finance_reviewed_at = models.DateTimeField(null=True, blank=True)

    PENDING = 'PENDING'
    CLEARED = 'CLEARED'
    FLAGGED = 'FLAGGED'

    FINANCE_STATUS_CHOICES = [
        (PENDING, 'Pending Finance Review'),
        (CLEARED, 'Cleared by Finance'),
        (FLAGGED, 'Flagged — Clarification Needed'),
    ]

    finance_status = models.CharField(
        max_length = 10,
        choices    = FINANCE_STATUS_CHOICES,
        default    = PENDING,
        db_index   = True,
    )
    finance_notes = models.TextField(
        blank     = True,
        help_text = 'Overall Finance reconciliation notes.',
    )

    # ── Clarification requests ────────────────────────────────
    clarification_requests = models.JSONField(
        default   = list,
        help_text = (
            'Array of clarification requests between Finance and BM. '
            'Structure: [{'
            '  "id": "uuid",'
            '  "section": "revenue",'
            '  "question": "Cash variance of GHS 45 on March 24 — explain.",'
            '  "asked_by": "Finance Name",'
            '  "asked_at": "ISO datetime",'
            '  "response": "Till was short due to...",'
            '  "responded_by": "BM Name",'
            '  "responded_at": "ISO datetime",'
            '  "resolved": true'
            '}]'
        ),
    )

    # ── Generation ────────────────────────────────────────────
    generated_at    = models.DateTimeField()
    last_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering            = ['-year', '-month']
        unique_together     = [['monthly_close']]
        indexes             = [
            models.Index(fields=['branch', 'year', 'month']),
            models.Index(fields=['finance_status']),
            models.Index(fields=['overall_risk_score']),
        ]
        verbose_name        = 'Monthly Close Summary'
        verbose_name_plural = 'Monthly Close Summaries'

    def __str__(self):
        return (
            f"{self.branch.code} | {self.month}/{self.year} "
            f"| risk={self.overall_risk_score} | {self.finance_status}"
        )

    @property
    def has_open_clarifications(self):
        """True if any clarification request has not been resolved."""
        return any(
            not req.get('resolved', False)
            for req in (self.clarification_requests or [])
        )

    @property
    def open_clarification_count(self):
        return sum(
            1 for req in (self.clarification_requests or [])
            if not req.get('resolved', False)
        )

    @property
    def risk_level(self):
        if self.overall_risk_score >= 70 or self.critical_days_count > 0:
            return 'CRITICAL'
        if self.overall_risk_score >= 50 or self.high_risk_days_count >= 3:
            return 'HIGH'
        if self.overall_risk_score >= 30:
            return 'MEDIUM'
        return 'LOW'