from django.db import models
from apps.core.models import AuditModel


class CashierFloat(AuditModel):
    """
    Records the opening float and closing cash count
    for each cashier on a given daily sheet.

    One record per cashier per day.
    Variance must be explained before the sheet can close.
    """

    daily_sheet = models.ForeignKey(
        'finance.DailySalesSheet',
        on_delete=models.PROTECT,
        related_name='cashier_floats',
        null=True, blank=True,
    )
    scheduled_date = models.DateField(
        null=True, blank=True,
        help_text='Date this float is scheduled for — set when pre-created at EOD',
    )
    cashier = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='cashier_floats',
    )

    # ── Opening ───────────────────────────────────────────────
    opening_float   = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Physical cash handed to cashier at day start',
    )
    float_set_by    = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='floats_set',
        null=True,
        blank=True,
    )
    float_set_at    = models.DateTimeField(null=True, blank=True)

    # ── Closing ───────────────────────────────────────────────
    closing_cash    = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Physical cash counted at day end by cashier',
    )
    expected_cash   = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Computed: opening float + cash collected - refunds - petty cash',
    )
    variance        = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Computed: closing cash - expected cash',
    )
    variance_notes  = models.TextField(
        blank=True,
        help_text='Mandatory explanation if variance is non-zero',
    )

    # ── Sign-off ──────────────────────────────────────────────
    signed_off_by   = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='floats_signed_off',
        null=True,
        blank=True,
    )
    signed_off_at   = models.DateTimeField(null=True, blank=True)
    is_signed_off   = models.BooleanField(default=False)
    shift_notes     = models.TextField(
        blank=True,
        help_text='Cashier notes on incidents or observations during shift',
    )

    # ── Overtime ──────────────────────────────────────────────
    is_overtime       = models.BooleanField(default=False)
    overtime_reason   = models.TextField(blank=True)
    overtime_until    = models.DateTimeField(null=True, blank=True)

    # ── Cover shift ───────────────────────────────────────────
    is_cover          = models.BooleanField(default=False)
    covering_for      = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='floats_covered_by',
        help_text='The cashier whose shift this person is covering',
    )
    cover_until       = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering        = ['-created_at']
        unique_together = [['daily_sheet', 'cashier']]
        verbose_name        = 'Cashier Float'
        verbose_name_plural = 'Cashier Floats'

    def __str__(self) -> str:
        return (
            f"{self.cashier.full_name} — "
            f"{self.daily_sheet.date} "
            f"(variance: {self.variance})"
        )

    def compute_variance(self) -> None:
        """
        Recompute expected cash and variance.
        Call this before closing the float record.
        """
        self.variance = self.closing_cash - self.expected_cash