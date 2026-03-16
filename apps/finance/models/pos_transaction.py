from django.db import models
from apps.core.models import AuditModel


class POSTransaction(AuditModel):
    """
    Records a POS card payment against a job.

    POS transactions have a settlement lag — the bank confirms
    funds the next business day. The sheet distinguishes between
    collected (approval code captured) and settled (bank confirmed).

    A transaction can be reversed by the bank silently — this is
    tracked via status and must trigger a BM notification.
    """

    class Status(models.TextChoices):
        PENDING   = 'PENDING',   'Pending Settlement'
        SETTLED   = 'SETTLED',   'Settled'
        REVERSED  = 'REVERSED',  'Reversed by Bank'

    job           = models.ForeignKey(
        'jobs.Job',
        on_delete=models.PROTECT,
        related_name='pos_transactions',
    )
    daily_sheet   = models.ForeignKey(
        'finance.DailySalesSheet',
        on_delete=models.PROTECT,
        related_name='pos_transactions',
    )
    cashier       = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='pos_transactions',
    )

    # ── Transaction details ───────────────────────────────────
    amount          = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )
    approval_code   = models.CharField(
        max_length=50,
        help_text='Approval code from POS terminal slip — mandatory',
    )
    terminal_id     = models.CharField(
        max_length=50,
        blank=True,
        help_text='POS terminal identifier',
    )

    # ── Settlement tracking ───────────────────────────────────
    status            = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    collected_date    = models.DateField()
    settlement_date   = models.DateField(
        null=True,
        blank=True,
        help_text='Date bank confirmed settlement',
    )
    settled_by        = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='pos_settlements',
        null=True,
        blank=True,
        help_text='Staff member who marked this as settled',
    )

    # ── Reversal ──────────────────────────────────────────────
    reversal_date     = models.DateField(
        null=True,
        blank=True,
    )
    reversal_notes    = models.TextField(
        blank=True,
        help_text='Explanation of bank reversal',
    )
    reversal_noted_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='pos_reversals_noted',
        null=True,
        blank=True,
    )

    class Meta:
        ordering        = ['-created_at']
        verbose_name        = 'POS Transaction'
        verbose_name_plural = 'POS Transactions'

    def __str__(self) -> str:
        return (
            f"POS {self.approval_code} — "
            f"GHS {self.amount} — "
            f"{self.status} — "
            f"{self.collected_date}"
        )

    @property
    def is_settled(self) -> bool:
        return self.status == self.Status.SETTLED

    @property
    def is_reversed(self) -> bool:
        return self.status == self.Status.REVERSED