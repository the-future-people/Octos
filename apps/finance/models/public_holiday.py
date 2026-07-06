from django.db import models
from apps.core.models import AuditModel


class PublicHoliday(AuditModel):
    """
    A date declared closed for business, separate from the permanent
    Sunday closure.

    Ghana's public holidays sometimes fall midweek but are observed
    on the following Friday by government directive — there is no
    reliable way to compute this from a calendar. Instead, a Branch
    Manager declares the actual observed closure date directly, and
    every portal (Cashier, Attendant) and the 5am sheet-opening task
    read from this record rather than deriving it.

    One record per branch per date — a holiday declared for one
    branch does not affect others.
    """

    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='public_holidays',
    )
    date = models.DateField()
    name = models.CharField(
        max_length=100,
        help_text='e.g. "Independence Day (observed)"',
    )
    declared_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='holidays_declared',
    )

    class Meta:
        ordering            = ['-date']
        unique_together     = [['branch', 'date']]
        verbose_name        = 'Public Holiday'
        verbose_name_plural  = 'Public Holidays'
        indexes = [
            models.Index(fields=['branch', 'date'], name='holiday_branch_date_idx'),
        ]

    def __str__(self):
        return f"{self.name} — {self.branch.code} — {self.date}"