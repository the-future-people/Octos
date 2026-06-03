# apps/accounts/models/staff_domain.py

from django.db import models
from apps.core.models import AuditModel


class StaffDomain(AuditModel):
    """
    Tracks the functional domain assigned to a Finance Deputy.
    A Deputy can have one or more domains.
    All Deputy actions within their domain require Head sign-off to take effect.

    Technical note: This is a junction/association model — it links two
    entities (CustomUser and Domain) with additional metadata (is_active).
    This pattern is called a Many-to-Many through model in Django.
    """

    class Domain(models.TextChoices):
        PAYROLL    = 'PAYROLL',    'Payroll'
        PROCUREMENT= 'PROCUREMENT','Procurement & Vendors'
        BUDGET     = 'BUDGET',     'Budget & Envelopes'
        REVIEWS    = 'REVIEWS',    'Monthly Close Reviews'
        REPORTING  = 'REPORTING',  'Analytics & Reporting'

    user      = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.CASCADE,
        related_name = 'domains',
    )
    domain    = models.CharField(max_length=20, choices=Domain.choices)
    is_active = models.BooleanField(default=True)
    assigned_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'domains_assigned',
        null         = True,
        blank        = True,
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering        = ['user', 'domain']
        unique_together = [['user', 'domain']]
        verbose_name        = 'Staff Domain'
        verbose_name_plural = 'Staff Domains'

    def __str__(self):
        return f"{self.user.full_name} — {self.get_domain_display()}"