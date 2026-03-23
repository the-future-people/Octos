from django.db import models
from django.utils import timezone
from apps.core.models import AuditModel


class Employee(AuditModel):
    """
    Central employee record. Created automatically by the onboarding engine.
    Every employee has a portal login (CustomUser) and is assigned to a branch.
    """

    # Pay Frequency
    MONTHLY = 'MONTHLY'
    BI_WEEKLY = 'BI_WEEKLY'
    WEEKLY = 'WEEKLY'

    PAY_FREQUENCY_CHOICES = [
        (MONTHLY, 'Monthly'),
        (BI_WEEKLY, 'Bi-Weekly'),
        (WEEKLY, 'Weekly'),
    ]

    # Employment Type
    FULL_TIME = 'FULL_TIME'
    PART_TIME = 'PART_TIME'
    CONTRACT = 'CONTRACT'

    EMPLOYMENT_TYPE_CHOICES = [
        (FULL_TIME, 'Full Time'),
        (PART_TIME, 'Part Time'),
        (CONTRACT, 'Contract'),
    ]

    # Status
    ACTIVE = 'ACTIVE'
    SUSPENDED = 'SUSPENDED'
    TERMINATED = 'TERMINATED'
    ON_LEAVE = 'ON_LEAVE'

    STATUS_CHOICES = [
        (ACTIVE, 'Active'),
        (SUSPENDED, 'Suspended'),
        (TERMINATED, 'Terminated'),
        (ON_LEAVE, 'On Leave'),
    ]

    # Core links
    user = models.OneToOneField(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='employee_profile'
    )
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='employees'
    )
    role = models.ForeignKey(
        'accounts.Role',
        on_delete=models.PROTECT,
        related_name='employees'
    )

    # Identity
    employee_number = models.CharField(max_length=30, unique=True, blank=True)
    national_id = models.CharField(max_length=50, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    profile_photo = models.ImageField(upload_to='employees/photos/', null=True, blank=True)

    # Employment details
    employment_type = models.CharField(
        max_length=20,
        choices=EMPLOYMENT_TYPE_CHOICES,
        default=FULL_TIME
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)
    date_joined = models.DateField(default=timezone.now)
    date_terminated = models.DateField(null=True, blank=True)

    # Payroll
    base_salary = models.DecimalField(max_digits=10, decimal_places=2)
    pay_frequency = models.CharField(
        max_length=20,
        choices=PAY_FREQUENCY_CHOICES,
        default=MONTHLY
    )
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_number = models.CharField(max_length=50, blank=True)
    mobile_money_number = models.CharField(max_length=20, blank=True)

    # RFID
    rfid_tag = models.CharField(max_length=100, unique=True, null=True, blank=True)

    # Onboarding
    onboarded_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='onboarded_employees'
    )
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['branch', 'role', 'user__first_name']

    def __str__(self):
        return f"{self.employee_number} — {self.full_name} ({self.branch.name})"

    def save(self, *args, **kwargs):
        if not self.employee_number:
            self.employee_number = self._generate_employee_number()
        super().save(*args, **kwargs)

    def _generate_employee_number(self):
        from django.utils import timezone
        year = timezone.now().year
        branch_code = self.branch.code if self.branch else 'GEN'
        last = Employee.objects.filter(
            branch=self.branch,
        ).count() + 1
        return f"FP-{branch_code}-{year}-{str(last).zfill(4)}"

    @property
    def full_name(self):
        return self.user.full_name

    @property
    def is_active(self):
        return self.status == self.ACTIVE