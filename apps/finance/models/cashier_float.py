from django.db import models
from apps.core.models import AuditModel


class CashierFloat(AuditModel):
    """
    Records a single cashier shift's float lifecycle.

    One record per cashier per shift per day.
    A branch with two cashier shifts in one day has two records.

    Lifecycle — single shift:
      1. BM stages float at EOD (daily_sheet=None, scheduled_date=tomorrow)
      2. Sheet opens at 7am → float auto-linked to sheet
      3. Cashier acknowledges receipt with denomination count
      4. Cashier works shift
      5a. Mid-day handover → cashier counts remaining float → hands to BM
          → system auto-stages same amount for next cashier
      5b. EOD sign-off → cashier counts cash collected → variance recorded
      6. BM closes sheet once all cashiers signed off

    shift_sequence:
      1 = first cashier of the day
      2 = second cashier (after mid-day handover)
      etc.

    Constraint: unique_together = [daily_sheet, cashier, shift_sequence]
    Allows same cashier to work two shifts (unusual but possible).
    """

    # ── Identity ──────────────────────────────────────────────
    daily_sheet = models.ForeignKey(
        'finance.DailySalesSheet',
        on_delete     = models.PROTECT,
        related_name  = 'cashier_floats',
        null          = True,
        blank         = True,
        help_text     = 'Null when staged — linked when sheet opens',
    )
    scheduled_date = models.DateField(
        null      = True,
        blank     = True,
        help_text = 'Date this float is scheduled for — set when pre-staged at EOD',
    )
    cashier = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'cashier_floats',
    )
    shift_sequence = models.PositiveSmallIntegerField(
        default   = 1,
        help_text = (
            'Order of this cashier shift within the day. '
            '1 = first cashier, 2 = second cashier after handover, etc.'
        ),
    )

    # ── Float set by BM ───────────────────────────────────────
    opening_float = models.DecimalField(
        max_digits   = 10,
        decimal_places = 2,
        default      = 0,
        help_text    = 'Physical cash handed to cashier at shift start',
    )
    float_set_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'floats_set',
        null         = True,
        blank        = True,
    )
    float_set_at = models.DateTimeField(null=True, blank=True)

    # ── Morning acknowledgement ───────────────────────────────
    morning_acknowledged = models.BooleanField(default=False)
    morning_acknowledged_at = models.DateTimeField(null=True, blank=True)
    opening_denomination_breakdown = models.JSONField(
        null      = True,
        blank     = True,
        help_text = (
            'Denomination count at float receipt. '
            'e.g. {"1":0,"2":0,"5":2,"10":0,"20":2,"50":0,"100":0,"200":0}'
        ),
    )

    # ── Mid-day handover ──────────────────────────────────────
    is_handover = models.BooleanField(
        default   = False,
        help_text = 'True if this shift ended mid-day with a handover to next cashier',
    )
    handover_float = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        null           = True,
        blank          = True,
        help_text      = 'Physical float amount counted and handed to BM at mid-day',
    )
    handover_denomination_breakdown = models.JSONField(
        null      = True,
        blank     = True,
        help_text = 'Denomination count at mid-day handover',
    )
    handover_at = models.DateTimeField(
        null      = True,
        blank     = True,
        help_text = 'When cashier handed float to BM',
    )
    handover_acknowledged_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.SET_NULL,
        null         = True,
        blank        = True,
        related_name = 'floats_handover_acknowledged',
        help_text    = 'BM who acknowledged receipt of handover float',
    )
    next_float = models.OneToOneField(
        'self',
        on_delete    = models.SET_NULL,
        null         = True,
        blank        = True,
        related_name = 'previous_float',
        help_text    = 'The next cashier float record this carries into',
    )

    # ── EOD sign-off ──────────────────────────────────────────
    closing_cash = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        default        = 0,
        help_text      = 'Physical cash counted at shift end by cashier',
    )
    expected_cash = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        default        = 0,
        help_text      = 'Computed: opening float + cash collected - petty cash',
    )
    variance = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        default        = 0,
        help_text      = 'Computed: closing cash - expected cash',
    )
    variance_notes = models.TextField(
        blank     = True,
        help_text = 'Mandatory explanation if variance is non-zero',
    )
    closing_denomination_breakdown = models.JSONField(
        null      = True,
        blank     = True,
        help_text = 'Denomination count at EOD cash count',
    )
    signed_off_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'floats_signed_off',
        null         = True,
        blank        = True,
    )
    signed_off_at = models.DateTimeField(null=True, blank=True)
    is_signed_off = models.BooleanField(default=False)
    shift_notes   = models.TextField(
        blank     = True,
        help_text = 'Cashier notes on incidents or observations during shift',
    )

    # ── Overtime ──────────────────────────────────────────────
    is_overtime     = models.BooleanField(default=False)
    overtime_reason = models.TextField(blank=True)
    overtime_until  = models.DateTimeField(null=True, blank=True)

    # ── Cover shift ───────────────────────────────────────────
    is_cover     = models.BooleanField(default=False)
    covering_for = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.SET_NULL,
        null         = True,
        blank        = True,
        related_name = 'floats_covered_by',
        help_text    = 'The cashier whose shift this person is covering',
    )
    cover_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [['daily_sheet', 'cashier', 'shift_sequence']]
        verbose_name        = 'Cashier Float'
        verbose_name_plural = 'Cashier Floats'
        indexes = [
            models.Index(fields=['daily_sheet', 'cashier']),
            models.Index(fields=['scheduled_date', 'cashier']),
            models.Index(fields=['is_signed_off']),
            models.Index(fields=['morning_acknowledged']),
        ]

    def __str__(self) -> str:
        date = (
            self.daily_sheet.date if self.daily_sheet
            else self.scheduled_date or '—'
        )
        shift = f" (shift {self.shift_sequence})" if self.shift_sequence > 1 else ''
        return f"{self.cashier.full_name} — {date}{shift} (variance: {self.variance})"

    # ── Float status — single source of truth ─────────────────

    @property
    def float_status(self):
        """
        Single source of truth for the cashier portal gate logic.

        NO_FLOAT        — no float record (handled by FloatEngine, not here)
        PENDING_ACK     — staged but cashier hasn't acknowledged
        ACTIVE          — acknowledged, shift in progress
        PENDING_HANDOVER— mid-day: cashier must count and hand over
        PENDING_SIGNOFF — EOD: cashier must count and sign off
        SIGNED_OFF      — fully signed off
        """
        if self.is_signed_off:
            return 'SIGNED_OFF'
        if self.is_handover and not self.handover_at:
            return 'PENDING_HANDOVER'
        if not self.morning_acknowledged:
            return 'PENDING_ACK'
        return 'ACTIVE'

    # ── Variance computation ───────────────────────────────────

    def compute_variance(self) -> None:
        """
        Recompute expected cash and variance.
        expected_cash = opening_float + cash_collected - petty_cash_out
        Call this before sign-off.
        """
        from apps.finance.models import Receipt, PettyCash
        from django.db.models import Sum

        if not self.daily_sheet:
            self.variance = self.closing_cash - self.opening_float
            return

        cash_collected = Receipt.objects.filter(
            daily_sheet    = self.daily_sheet,
            cashier        = self.cashier,
            payment_method = 'CASH',
            is_void        = False,
        ).aggregate(t=Sum('amount_paid'))['t'] or 0

        petty_cash_out = PettyCash.objects.filter(
            daily_sheet   = self.daily_sheet,
            cashier_float = self,
        ).aggregate(t=Sum('amount'))['t'] or 0

        self.expected_cash = (
            self.opening_float +
            cash_collected -
            petty_cash_out
        )
        self.variance = self.closing_cash - self.expected_cash

    # ── Denomination helpers ───────────────────────────────────

    @classmethod
    def denomination_total(cls, breakdown: dict) -> float:
        """
        Compute GHS total from denomination breakdown dict.
        e.g. {"1":2, "5":3, "20":1} → 2 + 15 + 20 = 37.0
        """
        if not breakdown:
            return 0.0
        return sum(
            int(denom) * int(count)
            for denom, count in breakdown.items()
        )

    @property
    def has_variance(self) -> bool:
        return abs(float(self.variance or 0)) > 0.01

    @property
    def variance_direction(self) -> str:
        v = float(self.variance or 0)
        if v > 0.01:
            return 'surplus'
        if v < -0.01:
            return 'shortage'
        return 'none'