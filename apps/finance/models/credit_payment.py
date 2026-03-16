from django.db import models
from apps.core.models import AuditModel


class CreditPayment(AuditModel):
    """
    Records a settlement payment against a credit account.

    A credit payment is not a job payment — it is a debt recovery
    transaction where a customer returns to settle their outstanding
    balance either partially or in full.

    These are recorded in the collections view, not the cashier portal.
    They appear on the daily sheet as CREDIT_SETTLEMENT — clearly
    separate from fresh revenue so the BM knows exactly what portion
    of today's cash is old debt being recovered.

    Payment method must be Cash, MoMo or POS — no credit on credit.
    """

    class PaymentMethod(models.TextChoices):
        CASH = 'CASH', 'Cash'
        MOMO = 'MOMO', 'Mobile Money'
        POS  = 'POS',  'POS'

    credit_account    = models.ForeignKey(
        'finance.CreditAccount',
        on_delete=models.PROTECT,
        related_name='payments',
    )
    daily_sheet       = models.ForeignKey(
        'finance.DailySalesSheet',
        on_delete=models.PROTECT,
        related_name='credit_payments',
    )
    received_by       = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='credit_payments_received',
    )

    # ── Payment details ───────────────────────────────────────
    amount            = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )
    payment_method    = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
    )
    momo_reference    = models.CharField(
        max_length=50,
        blank=True,
        help_text='Mandatory if payment method is MoMo',
    )
    pos_approval_code = models.CharField(
        max_length=50,
        blank=True,
        help_text='Mandatory if payment method is POS',
    )

    # ── Balance snapshot at time of payment ───────────────────
    balance_before    = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Credit account balance before this payment',
    )
    balance_after     = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Credit account balance after this payment',
    )

    # ── Receipt ───────────────────────────────────────────────
    receipt           = models.OneToOneField(
        'finance.Receipt',
        on_delete=models.PROTECT,
        related_name='credit_payment',
        null=True,
        blank=True,
        help_text='Auto-generated receipt for this settlement',
    )

    # ── Notes ─────────────────────────────────────────────────
    notes             = models.TextField(blank=True)

    class Meta:
        ordering        = ['-created_at']
        verbose_name        = 'Credit Payment'
        verbose_name_plural = 'Credit Payments'

    def __str__(self) -> str:
        return (
            f"{self.credit_account.customer.full_name} — "
            f"GHS {self.amount} — "
            f"{self.payment_method} — "
            f"{self.daily_sheet.date}"
        )

    @property
    def is_full_settlement(self) -> bool:
        """True if this payment cleared the entire outstanding balance."""
        return self.balance_after == 0