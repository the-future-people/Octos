from django.db import models
from apps.core.models import AuditModel


class CustomerWalletTransaction(AuditModel):
    """
    Immutable ledger of job-redeemable store credit — money the branch
    owes a customer (e.g. they overpaid and chose to save the difference
    for next time), NOT to be confused with CreditAccount, which tracks
    the opposite direction (money the customer owes the branch).

    These are deliberately separate systems. A customer can have a
    CreditAccount, a wallet balance, both, or neither — independent
    facts. See apps/finance/credit_engine.py for the debt side.

    Rules enforced elsewhere (cashier_service.py), not at the model
    layer:
      - customer must be a registered CustomerProfile, never a walk-in
      - every entry ties to a real job — never free-floating
      - job-redeemable only, never cash-redeemable
      - capped at GHS 200 per customer, overflow returned as cash
      - explicit customer consent required before CREDIT_ADDED
      - balance expires after 6 months of inactivity (EXPIRED entries,
        never silent deletion)
    """

    class TransactionType(models.TextChoices):
        CREDIT_ADDED   = 'CREDIT_ADDED',   'Credit Added'
        REDEEMED_JOB   = 'REDEEMED_JOB',   'Redeemed Against Job'
        EXPIRED        = 'EXPIRED',        'Expired'

    customer = models.ForeignKey(
        'customers.CustomerProfile',
        on_delete=models.PROTECT,
        related_name='wallet_transactions',
    )
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='wallet_transactions',
    )
    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.PROTECT,
        related_name='wallet_transactions',
        null=True, blank=True,
        help_text='Null only for EXPIRED entries — every CREDIT_ADDED '
                   'and REDEEMED_JOB entry must tie to a real job.',
    )

    transaction_type = models.CharField(max_length=15, choices=TransactionType.choices)
    amount           = models.DecimalField(max_digits=8, decimal_places=2)
    balance_before   = models.DecimalField(max_digits=8, decimal_places=2)
    balance_after    = models.DecimalField(max_digits=8, decimal_places=2)

    recorded_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='wallet_transactions_recorded',
        null=True, blank=True,
        help_text='Null only for EXPIRED entries — system-triggered, no human actor.',
    )
    consent_confirmed_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set only for CREDIT_ADDED — timestamp of explicit '
                   'customer consent captured by the cashier.',
    )

    class Meta:
        ordering     = ['-created_at']
        verbose_name = 'Customer Wallet Transaction'
        indexes = [
            models.Index(fields=['customer', 'created_at']),
            models.Index(fields=['branch', 'transaction_type']),
        ]

    def __str__(self):
        return f"{self.transaction_type} — {self.customer} — GHS {self.amount}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError(
                'CustomerWalletTransaction is immutable — create new '
                'entries, never update existing ones.'
            )
        super().save(*args, **kwargs)