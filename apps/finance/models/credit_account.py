from django.db import models
from apps.core.models import AuditModel


class CreditAccount(AuditModel):
    """
    A credit facility extended to a trusted customer —
    either an individual or an organisation (school, church, corporate).

    Credit limit is set and approved by a Belt Manager.
    The BM can recommend but cannot approve their own branch accounts.

    Rules:
    - System blocks job completion on credit if customer is at or over limit
    - BM can request a temporary override — Belt Manager approves
    - Account is suspended automatically if payment terms are breached
    - All credit issued and settlements are tracked separately on the daily sheet
    """

    class AccountType(models.TextChoices):
        INDIVIDUAL   = 'INDIVIDUAL',   'Individual'
        ORGANISATION = 'ORGANISATION', 'Organisation'

    class Status(models.TextChoices):
        PENDING   = 'PENDING',   'Pending Approval'
        ACTIVE    = 'ACTIVE',    'Active'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        CLOSED    = 'CLOSED',    'Closed'

    customer        = models.OneToOneField(
        'customers.CustomerProfile',
        on_delete=models.PROTECT,
        related_name='credit_account',
    )
    branch          = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='credit_accounts',
        null=True,
        blank=True,
    )
    account_type    = models.CharField(
        max_length=15,
        choices=AccountType.choices,
        default=AccountType.INDIVIDUAL,
    )
    status          = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    # ── Credit terms ──────────────────────────────────────────
    credit_limit      = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Maximum outstanding balance allowed',
    )
    current_balance   = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Running total of unpaid credit issued',
    )
    payment_terms     = models.PositiveIntegerField(
        default=30,
        help_text='Number of days customer has to settle balance',
    )

    # ── Organisation details (if applicable) ──────────────────
    organisation_name    = models.CharField(
        max_length=150,
        blank=True,
        help_text='School, church or company name',
    )
    contact_person       = models.CharField(
        max_length=100,
        blank=True,
        help_text='Primary contact at the organisation',
    )
    contact_phone        = models.CharField(
        max_length=20,
        blank=True,
    )

    # ── Approval — Belt Manager only ──────────────────────────
    nominated_by      = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='credit_accounts_nominated',
        null=True,
        blank=True,
        help_text='Branch Manager who nominated this account',
    )
    nominated_at      = models.DateTimeField(null=True, blank=True)
    approved_by       = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='credit_accounts_approved',
        null=True,
        blank=True,
        help_text='Belt Manager who approved this account',
    )
    approved_at       = models.DateTimeField(null=True, blank=True)

    # ── Suspension ────────────────────────────────────────────
    suspended_at      = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.TextField(blank=True)
    suspended_by      = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='credit_accounts_suspended',
        null=True,
        blank=True,
    )

    # ── Notes ─────────────────────────────────────────────────
    notes             = models.TextField(blank=True)

    class Meta:
        ordering        = ['-created_at']
        verbose_name        = 'Credit Account'
        verbose_name_plural = 'Credit Accounts'

    def __str__(self) -> str:
        name = self.organisation_name or self.customer.full_name
        return f"{name} — limit: GHS {self.credit_limit} — balance: GHS {self.current_balance}"

    @property
    def available_credit(self) -> float:
        """Remaining credit the customer can use."""
        return float(self.credit_limit) - float(self.current_balance)

    @property
    def is_over_limit(self) -> bool:
        return float(self.current_balance) >= float(self.credit_limit)

    @property
    def utilisation_pct(self) -> float:
        if not self.credit_limit:
            return 0
        return round((float(self.current_balance) / float(self.credit_limit)) * 100, 1)

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE