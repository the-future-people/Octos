from django.db import models
from apps.core.models import AuditModel


class DailySalesSheet(AuditModel):
    """
    Represents a single day's operations at a branch.
    One sheet per branch per day — auto-opened at 5am,
    auto-closed at 8:30pm after staged warnings.

    Revenue figures are computed live during the day
    and frozen at close. Numbers are never manually adjusted —
    BM can only add notes.
    """

    class Status(models.TextChoices):
        OPEN        = 'OPEN',        'Open'
        CLOSED      = 'CLOSED',      'Closed'
        AUTO_CLOSED = 'AUTO_CLOSED', 'Auto Closed'

    branch      = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='daily_sheets',
    )
    date        = models.DateField()
    status      = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.OPEN,
    )

    # ── Opening ───────────────────────────────────────────────
    opened_by   = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='sheets_opened',
        null=True, blank=True,   # null when auto-opened by system
    )
    opened_at   = models.DateTimeField(auto_now_add=True)

    # ── Closing ───────────────────────────────────────────────
    closed_by   = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='sheets_closed',
        null=True, blank=True,
    )
    closed_at   = models.DateTimeField(null=True, blank=True)

    # ── Stranded sheet recovery ───────────────────────────────
    # A sheet that could not be closed on its own day (outage, system
    # failure, oversight) strands every subsequent day, because the next
    # day's float is only staged during close. These fields record the
    # backdated reconciliation that unwinds that.
    class RecoveryReason(models.TextChoices):
        POWER_OUTAGE    = 'POWER_OUTAGE',    'Power outage'
        SYSTEM_DOWN     = 'SYSTEM_DOWN',     'System unavailable'
        NETWORK_FAILURE = 'NETWORK_FAILURE', 'Network failure'
        NOT_CLOSED      = 'NOT_CLOSED',      'Not closed at end of day'
        OTHER           = 'OTHER',           'Other'

    recovery_reason = models.CharField(
        max_length = 20,
        choices    = RecoveryReason.choices,
        blank      = True,
        help_text  = 'Why this sheet could not be closed on its own day',
    )
    recovered_at = models.DateTimeField(null=True, blank=True)
    recovered_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        null         = True,
        blank        = True,
        related_name = 'sheets_recovered',
        help_text    = 'Who keyed the recovery entry — not necessarily who counted the cash',
    )
    recovery_notes = models.TextField(
        blank     = True,
        help_text = 'Mandatory explanation recorded at recovery',
    )

    # ── Public holiday marker ─────────────────────────────────
    is_public_holiday    = models.BooleanField(default=False)
    public_holiday_name  = models.CharField(max_length=100, blank=True)

    # ── Frozen totals (computed at close, never edited) ───────
    total_jobs_created   = models.PositiveIntegerField(default=0)
    total_fresh_revenue  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_deposits       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_balances       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cash           = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_momo           = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_pos            = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_credit_issued   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_credit_settled  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_refunds        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_damages        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_petty_cash_out = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_cash_in_till     = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── VAT (future-proofed, 0 until GRA registered) ─────────
    vat_collected        = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Sheet number (branch-scoped, cumulative) ──────────────────────────
    sheet_number         = models.CharField(max_length=20, blank=True, default='')

    # ── Notes (BM only, no number adjustments) ───────────────────────────
    notes                = models.TextField(blank=True)

    # ── Disruption tracking ───────────────────────────────────────────────
    class DisruptionReason(models.TextChoices):
        POWER_OUTAGE       = 'POWER_OUTAGE',       'Power Outage'
        FLOODING           = 'FLOODING',           'Flooding'
        SECURITY_INCIDENT  = 'SECURITY_INCIDENT',  'Security Incident'
        FORCE_MAJEURE      = 'FORCE_MAJEURE',       'Force Majeure'
        OTHER              = 'OTHER',              'Other'

    class DisruptionStatus(models.TextChoices):
        PENDING_REVIEW = 'PENDING_REVIEW', 'Pending Review'
        APPROVED       = 'APPROVED',       'Approved'
        REJECTED       = 'REJECTED',       'Rejected'

    disruption_reason      = models.CharField(
        max_length=20,
        choices=DisruptionReason.choices,
        null=True, blank=True,
    )
    disruption_evidence    = models.TextField(
        blank=True,
        help_text='URL, ECG reference, news link, or other provable evidence',
    )
    disruption_notes       = models.TextField(blank=True)
    disruption_status      = models.CharField(
        max_length=15,
        choices=DisruptionStatus.choices,
        null=True, blank=True,
    )
    disruption_submitted_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='disruptions_submitted',
        null=True, blank=True,
    )
    disruption_submitted_at = models.DateTimeField(null=True, blank=True)
    disruption_reviewed_by  = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='disruptions_reviewed',
        null=True, blank=True,
    )
    disruption_reviewed_at      = models.DateTimeField(null=True, blank=True)
    disruption_rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering             = ['-date']
        unique_together      = [['branch', 'date']]
        verbose_name         = 'Daily Sales Sheet'
        verbose_name_plural  = 'Daily Sales Sheets'
        indexes = [
            models.Index(fields=['branch', 'date'],   name='sheet_branch_date_idx'),
            models.Index(fields=['branch', 'status'], name='sheet_branch_status_idx'),
            models.Index(fields=['status'],           name='sheet_status_idx'),
        ]
        indexes = [
            models.Index(fields=['branch', 'date'],   name='sheet_branch_date_idx'),
            models.Index(fields=['branch', 'status'], name='sheet_branch_status_idx'),
            models.Index(fields=['status'],           name='sheet_status_idx'),
        ]

    def __str__(self):
        ref = self.sheet_number or str(self.pk)
        return f"{ref} — {self.date} [{self.status}]"

    @property
    def is_open(self):
        return self.status == self.Status.OPEN

    @property
    def total_collected(self):
        """Total cash actually received — excludes credit issued."""
        return self.total_cash + self.total_momo + self.total_pos + self.total_credit_settled

    @property
    def is_disrupted(self):
        """True if this day was a legitimate non-operating day."""
        return bool(self.disruption_reason)

    @property
    def disruption_approved(self):
        """True only if the disruption has been reviewed and approved by the owner."""
        return self.disruption_status == self.DisruptionStatus.APPROVED