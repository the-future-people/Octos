from django.db import models
from apps.core.models import AuditModel


class PettyCash(AuditModel):
    """
    Records petty cash disbursements from the till during the day.

    Every petty cash out requires BM approval and a clear purpose.
    These reduce the expected cash in till at reconciliation.
    Petty cash is never adjusted retroactively — if recorded wrongly,
    a corrective entry is made with a note, never a deletion.
    """

    class Category(models.TextChoices):
        SUPPLIES     = 'SUPPLIES',     'Supplies'
        TRANSPORT    = 'TRANSPORT',    'Transport'
        UTILITIES    = 'UTILITIES',    'Utilities'
        MAINTENANCE  = 'MAINTENANCE',  'Maintenance'
        WELFARE      = 'WELFARE',      'Staff Welfare'
        OTHER        = 'OTHER',        'Other'

    daily_sheet  = models.ForeignKey(
        'finance.DailySalesSheet',
        on_delete=models.PROTECT,
        related_name='petty_cash_entries',
    )
    cashier_float = models.ForeignKey(
        'finance.CashierFloat',
        on_delete=models.PROTECT,
        related_name='petty_cash_entries',
        help_text='Which cashier float this came out of',
    )
    amount       = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )
    category     = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.OTHER,
    )
    purpose      = models.TextField(
        help_text='Clear description of what the cash was used for',
    )

    # ── Approval ──────────────────────────────────────────────
    approved_by  = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='petty_cash_approvals',
    )
    approved_at  = models.DateTimeField()

    # ── Recording ─────────────────────────────────────────────
    recorded_by  = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='petty_cash_recorded',
    )

    # ── Correction flag ───────────────────────────────────────
    is_correction      = models.BooleanField(
        default=False,
        help_text='True if this entry corrects a prior erroneous entry',
    )
    corrects_entry     = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='correction_entries',
        help_text='The original entry this corrects',
    )

    class Meta:
        ordering        = ['-created_at']
        verbose_name        = 'Petty Cash Entry'
        verbose_name_plural = 'Petty Cash Entries'

    def __str__(self) -> str:
        return (
            f"{self.daily_sheet.branch.code} — "
            f"GHS {self.amount} — "
            f"{self.category} — "
            f"{self.daily_sheet.date}"
        )