from django.db import models
from apps.core.models import AuditModel


class CustomerProfile(AuditModel):
    """
    Created automatically when a customer visits more than once.
    Phone number is the primary identifier across all channels.
    """

    # Loyalty Tiers
    REGULAR   = 'REGULAR'
    PREFERRED = 'PREFERRED'
    VIP       = 'VIP'

    TIER_CHOICES = [
        (REGULAR,   'Regular'),
        (PREFERRED, 'Preferred'),
        (VIP,       'VIP'),
    ]

    first_name = models.CharField(max_length=100, blank=True)
    last_name  = models.CharField(max_length=100, blank=True)
    phone      = models.CharField(max_length=20, unique=True)
    email      = models.EmailField(blank=True)
    visit_count = models.PositiveIntegerField(default=1)
    tier       = models.CharField(
        max_length=20,
        choices=TIER_CHOICES,
        default=REGULAR,
    )
    preferred_branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='preferred_customers',
    )
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customers',
        help_text='Branch where this customer was first recorded',
    )
    is_priority = models.BooleanField(default=False)
    is_walkin   = models.BooleanField(
        default=False,
        help_text='True if auto-created from a walk-in receipt delivery',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-visit_count', 'first_name']

    def __str__(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return f"{name} ({self.phone})" if name else self.phone

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()