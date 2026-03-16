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
    total_credit_issued  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_refunds        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_damages        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_petty_cash_out = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_cash_in_till     = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── VAT (future-proofed, 0 until GRA registered) ─────────
    vat_collected        = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Notes (BM only, no number adjustments) ───────────────
    notes                = models.TextField(blank=True)

    class Meta:
        ordering             = ['-date']
        unique_together      = [['branch', 'date']]
        verbose_name         = 'Daily Sales Sheet'
        verbose_name_plural  = 'Daily Sales Sheets'

    def __str__(self):
        return f"{self.branch.code} — {self.date} [{self.status}]"

    @property
    def is_open(self):
        return self.status == self.Status.OPEN

    @property
    def total_collected(self):
        """Total cash actually received — excludes credit issued."""
        return self.total_cash + self.total_momo + self.total_pos