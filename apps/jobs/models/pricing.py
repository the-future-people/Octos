from django.db import models
from apps.core.models import AuditModel


class PricingRule(AuditModel):
    """
    Defines the price for a service.
    Branch-specific rules override company-wide defaults.
    If branch is null, it is the company-wide default.
    """
    service = models.ForeignKey(
        'jobs.Service',
        on_delete=models.PROTECT,
        related_name='pricing_rules'
    )
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.CASCADE,
        related_name='pricing_rules',
        null=True,
        blank=True,
        help_text='Leave blank for company-wide default'
    )
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    color_multiplier = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=1.00,
        help_text='Multiplier for color jobs e.g. 1.5 means color costs 1.5x base price'
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['service', 'branch']
        unique_together = [['service', 'branch']]

    def __str__(self):
        branch_name = self.branch.name if self.branch else 'Company Default'
        return f"{self.service.name} — {branch_name} @ GHS {self.base_price}"


class PriceOverrideLog(AuditModel):
    """
    Every manual price override is logged here.
    No price change ever goes unrecorded.
    """
    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.PROTECT,
        related_name='price_overrides'
    )
    original_price = models.DecimalField(max_digits=10, decimal_places=2)
    overridden_price = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    authorized_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='price_overrides'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.job.job_number} — GHS {self.original_price} → GHS {self.overridden_price}"