# apps/finance/models/monthly_close.py

from django.db import models
from django.utils import timezone
from apps.core.models import AuditModel


class MonthlyClose(AuditModel):
    """
    End-of-month closure record for a branch.

    Lifecycle:
      OPEN                — month is active, not yet submitted
      SUBMITTED           — BM has signed off; awaiting Finance assignment
      FINANCE_REVIEWING   — Finance reviewer assigned and actively reviewing
      NEEDS_CLARIFICATION — Finance has flagged items; BM has 24h to respond
      RESUBMITTED         — BM responded to clarification; back to Finance
      FINANCE_CLEARED     — Finance has approved; awaiting RM endorsement
      ENDORSED            — RM has endorsed; month finalised
      LOCKED              — PDF downloaded; permanently immutable
      REJECTED            — RM rejected at any post-SUBMITTED stage

    Integrity gates for BM submission (ALL must be true):
      1. All daily sheets for the month are CLOSED or AUTO_CLOSED
      2. All weekly filings for the month are SUBMITTED or LOCKED
      3. No jobs in PENDING_PAYMENT state from this month
      4. No unsigned cashier floats from this month

    Once LOCKED — permanently immutable:
      - No backdating of jobs
      - No edits to any daily sheet or weekly filing
      - PDF download logged: who, when, IP
    """

    class Status(models.TextChoices):
        OPEN                = 'OPEN',                'Open'
        SUBMITTED           = 'SUBMITTED',           'Submitted — Awaiting Finance Review'
        FINANCE_REVIEWING   = 'FINANCE_REVIEWING',   'Finance Reviewing'
        NEEDS_CLARIFICATION = 'NEEDS_CLARIFICATION', 'Needs Clarification'
        RESUBMITTED         = 'RESUBMITTED',         'Resubmitted — Finance Re-reviewing'
        FINANCE_CLEARED     = 'FINANCE_CLEARED',     'Finance Cleared — Awaiting RM Endorsement'
        ENDORSED            = 'ENDORSED',            'Endorsed by RM'
        LOCKED              = 'LOCKED',              'Locked'
        REJECTED            = 'REJECTED',            'Rejected'

    branch = models.ForeignKey(
        'organization.Branch',
        on_delete    = models.PROTECT,
        related_name = 'monthly_closes',
    )
    month  = models.PositiveIntegerField(help_text='Month number 1–12')
    year   = models.PositiveIntegerField()
    status = models.CharField(
        max_length = 20,
        choices    = Status.choices,
        default    = Status.OPEN,
    )

    # ── Summary snapshot (frozen at submit time) ──────────────────────────
    summary_snapshot = models.JSONField(
        default   = dict,
        blank     = True,
        help_text = 'Full month summary frozen at submission time',
    )

    # ── BM sign-off ───────────────────────────────────────────────────────
    submitted_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'monthly_closes_submitted',
        null=True, blank=True,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    bm_notes     = models.TextField(blank=True)

    # ── Finance review ────────────────────────────────────────────────────
    finance_reviewer  = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'monthly_closes_reviewing',
        null=True, blank=True,
    )
    finance_assigned_at = models.DateTimeField(null=True, blank=True)
    finance_cleared_at  = models.DateTimeField(null=True, blank=True)
    finance_notes       = models.TextField(blank=True)

    # ── Clarification loop ────────────────────────────────────────────────
    clarification_request  = models.TextField(blank=True)
    clarification_response = models.TextField(blank=True)
    clarification_due_at   = models.DateTimeField(null=True, blank=True)

    # ── RM endorsement ────────────────────────────────────────────────────
    endorsed_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'monthly_closes_endorsed',
        null=True, blank=True,
    )
    endorsed_at = models.DateTimeField(null=True, blank=True)
    rm_notes    = models.TextField(blank=True)
    locked_at   = models.DateTimeField(null=True, blank=True)

    # ── Rejection ─────────────────────────────────────────────────────────
    rejected_by      = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'monthly_closes_rejected',
        null=True, blank=True,
    )
    rejected_at      = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    # ── PDF ───────────────────────────────────────────────────────────────
    pdf_path        = models.CharField(max_length=500, blank=True)
    pdf_downloaded_at = models.DateTimeField(null=True, blank=True)
    pdf_downloaded_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'monthly_closes_pdf_downloads',
        null=True, blank=True,
    )

    class Meta:
        ordering        = ['-year', '-month']
        unique_together = [['branch', 'month', 'year']]
        verbose_name        = 'Monthly Close'
        verbose_name_plural = 'Monthly Closes'

    def __str__(self):
        import calendar
        return f"{self.branch.code} — {calendar.month_name[self.month]} {self.year} [{self.status}]"

    @property
    def month_name(self):
        import calendar
        return calendar.month_name[self.month]

    # ── State checks ──────────────────────────────────────────────────────

    @property
    def is_locked(self):
        return self.status == self.Status.LOCKED

    @property
    def can_submit(self):
        """BM can submit from OPEN or after a REJECTED close."""
        return self.status in [self.Status.OPEN, self.Status.REJECTED]

    @property
    def can_assign_finance(self):
        """System assigns Finance reviewer when BM submits."""
        return self.status == self.Status.SUBMITTED

    @property
    def can_request_clarification(self):
        """Finance can flag items for clarification."""
        return self.status in [
            self.Status.FINANCE_REVIEWING,
            self.Status.RESUBMITTED,
        ]

    @property
    def can_respond_clarification(self):
        """BM can respond to a clarification request."""
        return self.status == self.Status.NEEDS_CLARIFICATION

    @property
    def can_clear(self):
        """Finance can clear (approve) the close."""
        return self.status in [
            self.Status.FINANCE_REVIEWING,
            self.Status.RESUBMITTED,
        ]

    @property
    def can_endorse(self):
        """RM can endorse only after Finance has cleared."""
        return self.status == self.Status.FINANCE_CLEARED

    @property
    def can_reject(self):
        """RM can reject at any post-SUBMITTED stage."""
        return self.status in [
            self.Status.SUBMITTED,
            self.Status.FINANCE_REVIEWING,
            self.Status.NEEDS_CLARIFICATION,
            self.Status.RESUBMITTED,
            self.Status.FINANCE_CLEARED,
        ]

    @property
    def can_lock(self):
        """Locks after RM endorsement (triggered on PDF download)."""
        return self.status == self.Status.ENDORSED