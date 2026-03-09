from django.db import models
from apps.core.models import AuditModel


class JobPosition(AuditModel):
    """
    An open position at a specific branch that can be recruited for.
    Every application must be tied to an open position.
    """

    # Status
    OPEN = 'OPEN'
    CLOSED = 'CLOSED'
    ON_HOLD = 'ON_HOLD'
    FILLED = 'FILLED'

    STATUS_CHOICES = [
        (OPEN, 'Open'),
        (CLOSED, 'Closed'),
        (ON_HOLD, 'On Hold'),
        (FILLED, 'Filled'),
    ]

    title = models.CharField(max_length=150)
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='open_positions'
    )
    role = models.ForeignKey(
        'accounts.Role',
        on_delete=models.PROTECT,
        related_name='positions'
    )
    description = models.TextField(blank=True)
    requirements = models.TextField(blank=True)
    vacancies = models.PositiveIntegerField(default=1)
    employment_type = models.CharField(
        max_length=20,
        choices=[
            ('FULL_TIME', 'Full Time'),
            ('PART_TIME', 'Part Time'),
            ('CONTRACT', 'Contract'),
        ],
        default='FULL_TIME'
    )
    base_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN)
    opens_at = models.DateField()
    closes_at = models.DateField()
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='created_positions'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} — {self.branch.name} ({self.status})"

    @property
    def is_open(self):
        from django.utils import timezone
        today = timezone.now().date()
        return self.status == self.OPEN and self.opens_at <= today <= self.closes_at