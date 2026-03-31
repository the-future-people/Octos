from django.db import models
from apps.core.models import AuditModel


class CashierFloat(AuditModel):
    """
    Records the opening float and closing cash count
    for each cashier on a given daily sheet.

    One record per cashier per day.

    Lifecycle:
      1. BM stages float at EOD (daily_sheet=None, scheduled_date=tomorrow)
      2. Sheet opens → float auto-linked to sheet
      3. Cashier acknowledges receipt with denomination breakdown (morning_acknowledged)
      4. Cashier works shift
      5. Cashier submits closing cash with denomination breakdown + signs off (is_signed_off)
      6. BM can close sheet once all cashiers signed off
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
    opening_float = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Physical cash handed to cashier at day start',
    )
    float_set_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='floats_set',
        null=True, blank=True,
    )
    float_set_at = models.DateTimeField(null=True, blank=True)

    # ── Morning acknowledgement ───────────────────────────────
    morning_acknowledged    = models.BooleanField(default=False)
    morning_acknowledged_at = models.DateTimeField(null=True, blank=True)
    opening_denomination_breakdown = models.JSONField(
        null=True, blank=True,
        help_text=(
            'Denomination count at float receipt — '
            'e.g. {"1":0,"2":0,"5":2,"10":0,"20":2,"50":0,"100":0,"200":0}'
        ),
    )

    # ── Closing ───────────────────────────────────────────────
    closing_cash = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Physical cash counted at day end by cashier',
    )
    expected_cash = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Computed: opening float + cash collected - refunds - petty cash',
    )
    variance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Computed: closing cash - expected cash',
    )
    variance_notes = models.TextField(
        blank=True,
        help_text='Mandatory explanation if variance is non-zero',
    )
    closing_denomination_breakdown = models.JSONField(
        null=True, blank=True,
        help_text=(
            'Denomination count at EOD cash count — '
            'same structure as opening_denomination_breakdown'
        ),
    )

    # ── Sign-off ──────────────────────────────────────────────
    signed_off_by  = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='floats_signed_off',
        null=True, blank=True,
    )
    signed_off_at  = models.DateTimeField(null=True, blank=True)
    is_signed_off  = models.BooleanField(default=False)
    shift_notes    = models.TextField(
        blank=True,
        help_text='Cashier notes on incidents or observations during shift',
    )

    # ── Overtime ──────────────────────────────────────────────
    is_overtime     = models.BooleanField(default=False)
    overtime_reason = models.TextField(blank=True)
    overtime_until  = models.DateTimeField(null=True, blank=True)

    # ── Cover shift ───────────────────────────────────────────
    is_cover   = models.BooleanField(default=False)
    covering_for = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='floats_covered_by',
        help_text='The cashier whose shift this person is covering',
    )
    cover_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering        = ['-created_at']
        unique_together = [['daily_sheet', 'cashier']]
        verbose_name        = 'Cashier Float'
        verbose_name_plural = 'Cashier Floats'

    def __str__(self) -> str:
        date = (
            self.daily_sheet.date if self.daily_sheet
            else self.scheduled_date or '—'
        )
        return (
            f"{self.cashier.full_name} — "
            f"{date} "
            f"(variance: {self.variance})"
        )

    def compute_variance(self) -> None:
        """
        Recompute expected cash and variance.
        Call this before closing the float record.
        """
        self.variance = self.closing_cash - self.expected_cash

    @property
    def float_status(self):
        """
        Single source of truth for the cashier portal's gate logic.

        NO_FLOAT        — no float record exists for today
        PENDING_ACK     — float staged but cashier hasn't confirmed receipt
        ACTIVE          — cashier acknowledged, working normally
        PENDING_SIGNOFF — shift ended, cashier must count and submit
        SIGNED_OFF      — fully signed off for the day
        """
        if self.is_signed_off:
            return 'SIGNED_OFF'
        if not self.morning_acknowledged:
            return 'PENDING_ACK'
        return 'ACTIVE'

    @classmethod
    def denomination_total(cls, breakdown: dict) -> float:
        """
        Compute GHS total from a denomination breakdown dict.
        e.g. {"1":2, "5":3, "20":1} → 2 + 15 + 20 = 37.0
        """
        if not breakdown:
            return 0.0
        return sum(int(denom) * int(count) for denom, count in breakdown.items())