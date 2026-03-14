from django.db import models
from apps.core.models import AuditModel
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


class PricingRule(AuditModel):
    """
    Defines the price for a service.
    Branch-specific rules override company-wide defaults.
    If branch is null, it is the company-wide default.

    pricing_tiers: optional JSON for tiered pricing logic.
    If present, overrides base_price calculation.

    Per-page tier example (Typing):
    [
        {"min": 1,  "max": 5,    "price_per_unit": 20.00},
        {"min": 6,  "max": null, "price_per_unit": 15.00}
    ]

    Flat-fee tier example (Binding):
    [
        {"min": 1,   "max": 100,  "flat_price": 10.00},
        {"min": 101, "max": 200,  "flat_price": 20.00},
        {"min": 201, "max": null, "flat_price": 40.00}
    ]
    """
    service = models.ForeignKey(
        'jobs.Service',
        on_delete=models.PROTECT,
        related_name='pricing_rules',
    )
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.CASCADE,
        related_name='pricing_rules',
        null=True,
        blank=True,
        help_text='Leave blank for company-wide default',
    )
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )
    color_multiplier = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=1.00,
        help_text='Multiplier for color jobs e.g. 1.5 means color costs 1.5x base price',
    )
    pricing_tiers = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            'Optional tiered pricing. If set, overrides base_price calculation. '
            'Use price_per_unit for per-unit tiers (Typing), '
            'flat_price for flat-fee tiers (Binding).'
        ),
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering        = ['service', 'branch']
        unique_together = [['service', 'branch']]

    def __str__(self) -> str:
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
        related_name='price_overrides',
    )
    original_price = models.DecimalField(max_digits=10, decimal_places=2)
    overridden_price = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    authorized_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='price_overrides',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return (
            f"{self.job.job_number} — "
            f"GHS {self.original_price} → GHS {self.overridden_price}"
        )