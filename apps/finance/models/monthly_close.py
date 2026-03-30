from django.db import models
from apps.core.models import AuditModel


class MonthlyClose(AuditModel):
    """
    End-of-month closure record for a branch.

    Lifecycle:
      OPEN      — month is active, not yet submitted
      SUBMITTED — BM has signed off, awaiting Belt Manager endorsement
      ENDORSED  — Belt Manager has approved, month is finalized
      REJECTED  — Belt Manager rejected, BM must resolve and resubmit

    Trigger conditions for BM submission (ALL must be true):
      1. Today is the last calendar day of the month
      2. All daily sheets for the month are CLOSED or AUTO_CLOSED
      3. All weekly filings for the month are SUBMITTED or LOCKED
      4. No jobs in PENDING_PAYMENT state from this month
      5. No unsigned cashier floats from this month

    Once ENDORSED — the month is permanently locked:
      - No backdating of jobs
      - No edits to any daily sheet or weekly filing
      - PDF available for download
    """

    class Status(models.TextChoices):
        OPEN      = 'OPEN',      'Open'
        SUBMITTED = 'SUBMITTED', 'Submitted — Awaiting Endorsement'
        ENDORSED  = 'ENDORSED',  'Endorsed & Finalized'
        REJECTED  = 'REJECTED',  'Rejected — Resubmission Required'

    branch  = models.ForeignKey(
        'organization.Branch',
        on_delete    = models.PROTECT,
        related_name = 'monthly_closes',
    )
    month   = models.PositiveIntegerField(help_text='Month number 1–12')
    year    = models.PositiveIntegerField()
    status  = models.CharField(
        max_length = 12,
        choices    = Status.choices,
        default    = Status.OPEN,
    )

    # ── Summary snapshot (frozen at submit time) ──────────────────────────
    summary_snapshot = models.JSONField(
        default  = dict,
        blank    = True,
        help_text= 'Full month summary frozen at submission time',
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

    # ── Belt Manager endorsement ──────────────────────────────────────────
    endorsed_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'monthly_closes_endorsed',
        null=True, blank=True,
    )
    endorsed_at = models.DateTimeField(null=True, blank=True)
    belt_notes  = models.TextField(blank=True)

    # ── Rejection ─────────────────────────────────────────────────────────
    rejected_by       = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'monthly_closes_rejected',
        null=True, blank=True,
    )
    rejected_at       = models.DateTimeField(null=True, blank=True)
    rejection_reason  = models.TextField(blank=True)

    # ── PDF ───────────────────────────────────────────────────────────────
    pdf_path = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering        = ['-year', '-month']
        unique_together = [['branch', 'month', 'year']]
        verbose_name        = 'Monthly Close'
        verbose_name_plural = 'Monthly Closes'

    def __str__(self):
        import calendar
        month_name = calendar.month_name[self.month]
        return f"{self.branch.code} — {month_name} {self.year} [{self.status}]"

    @property
    def month_name(self):
        import calendar
        return calendar.month_name[self.month]

    @property
    def is_locked(self):
        return self.status == self.Status.ENDORSED

    @property
    def can_submit(self):
        return self.status in [self.Status.OPEN, self.Status.REJECTED]

    @property
    def can_endorse(self):
        return self.status == self.Status.SUBMITTED

    @property
    def can_reject(self):
        return self.status == self.Status.SUBMITTED