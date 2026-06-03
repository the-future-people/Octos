# apps/procurement/models/budget.py

from django.db import models
from apps.core.models import AuditModel


class AnnualBudget(AuditModel):
    """
    Top-level annual budget proposed by Finance and approved by Owner.
    On approval, quarterly and bi-yearly envelopes are auto-generated.
    """

    class Status(models.TextChoices):
        DRAFT            = 'DRAFT',            'Draft'
        PENDING_APPROVAL = 'PENDING_APPROVAL', 'Pending Owner Approval'
        APPROVED         = 'APPROVED',         'Approved'
        CLOSED           = 'CLOSED',           'Closed'

    year   = models.PositiveIntegerField(unique=True)
    status = models.CharField(
        max_length = 20,
        choices    = Status.choices,
        default    = Status.DRAFT,
    )
    proposed_by  = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'budgets_proposed',
    )
    approved_by  = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'budgets_approved',
        null         = True,
        blank        = True,
    )
    approved_at  = models.DateTimeField(null=True, blank=True)
    notes        = models.TextField(blank=True)

    class Meta:
        ordering            = ['-year']
        verbose_name        = 'Annual Budget'
        verbose_name_plural = 'Annual Budgets'

    def __str__(self):
        return f"Budget {self.year} [{self.status}]"

    @property
    def can_approve(self):
        return self.status == self.Status.PENDING_APPROVAL

    @property
    def can_submit(self):
        return self.status == self.Status.DRAFT


class BudgetEnvelope(AuditModel):
    """
    A budget allocation for a specific category and period.
    Auto-generated from AnnualBudget on approval.

    Period types:
      ANNUAL     — full year view
      BI_YEARLY  — H1 (Jan–Jun) or H2 (Jul–Dec)
      QUARTERLY  — Q1/Q2/Q3/Q4

    Carry-forward: unspent balance from previous period
    rolls into the next period's available amount.
    """

    class PeriodType(models.TextChoices):
        ANNUAL     = 'ANNUAL',     'Annual'
        BI_YEARLY  = 'BI_YEARLY',  'Bi-Yearly'
        QUARTERLY  = 'QUARTERLY',  'Quarterly'

    class Period(models.TextChoices):
        ANNUAL = 'ANNUAL', 'Full Year'
        H1     = 'H1',     'H1 (Jan–Jun)'
        H2     = 'H2',     'H2 (Jul–Dec)'
        Q1     = 'Q1',     'Q1 (Jan–Mar)'
        Q2     = 'Q2',     'Q2 (Apr–Jun)'
        Q3     = 'Q3',     'Q3 (Jul–Sep)'
        Q4     = 'Q4',     'Q4 (Oct–Dec)'

    class Category(models.TextChoices):
        STOCK         = 'STOCK',         'Stock & Materials'
        PAYROLL       = 'PAYROLL',        'Payroll'
        MAINTENANCE   = 'MAINTENANCE',   'Maintenance'
        MARKETING     = 'MARKETING',     'Marketing'
        INVESTMENT    = 'INVESTMENT',    'Investment'
        UTILITIES     = 'UTILITIES',     'Utilities'
        EQUIPMENT     = 'EQUIPMENT',     'Equipment'
        MISCELLANEOUS = 'MISCELLANEOUS', 'Miscellaneous'

    class Status(models.TextChoices):
        ACTIVE    = 'ACTIVE',    'Active'
        EXHAUSTED = 'EXHAUSTED', 'Exhausted'
        CLOSED    = 'CLOSED',    'Closed'

    budget      = models.ForeignKey(
        AnnualBudget,
        on_delete    = models.CASCADE,
        related_name = 'envelopes',
    )
    period_type = models.CharField(max_length=10, choices=PeriodType.choices)
    period      = models.CharField(max_length=10, choices=Period.choices)
    category    = models.CharField(max_length=20, choices=Category.choices)
    status      = models.CharField(
        max_length = 10,
        choices    = Status.choices,
        default    = Status.ACTIVE,
    )

    ceiling          = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Proposed ceiling amount for this envelope.',
    )
    approved_amount  = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Amount approved by Owner.',
    )
    spent            = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Amount spent to date — auto-updated on procurement clearance.',
    )
    carry_forward    = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Unspent balance carried forward from previous period.',
    )

    class Meta:
        ordering        = ['budget__year', 'period_type', 'category']
        unique_together = [['budget', 'period', 'category']]
        verbose_name        = 'Budget Envelope'
        verbose_name_plural = 'Budget Envelopes'

    def __str__(self):
        return f"{self.budget.year} {self.period} {self.category} — GHS {self.available}"

    @property
    def available(self):
        return self.approved_amount + self.carry_forward - self.spent

    @property
    def utilisation_pct(self):
        total = self.approved_amount + self.carry_forward
        if not total:
            return 0
        return round(float(self.spent) / float(total) * 100, 1)

    def deduct(self, amount):
        """Deduct amount from envelope when procurement is approved."""
        from decimal import Decimal
        from django.db import transaction
        amount = Decimal(str(amount))
        with transaction.atomic():
            self.spent += amount
            if self.spent >= (self.approved_amount + self.carry_forward):
                self.status = self.Status.EXHAUSTED
            self.save(update_fields=['spent', 'status', 'updated_at'])