from django.db import models
from apps.core.models import AuditModel


class OnboardingRecord(AuditModel):
    """
    Captures all details needed to fully onboard a new employee.
    Created automatically when an applicant accepts an offer.
    Completion triggers Employee record creation and portal account setup.
    """

    # Status
    IN_PROGRESS = 'IN_PROGRESS'
    COMPLETED = 'COMPLETED'
    CANCELLED = 'CANCELLED'

    STATUS_CHOICES = [
        (IN_PROGRESS, 'In Progress'),
        (COMPLETED, 'Completed'),
        (CANCELLED, 'Cancelled'),
    ]

    applicant = models.OneToOneField(
        'hr.Applicant',
        on_delete=models.PROTECT,
        related_name='onboarding'
    )
    conducted_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='onboarding_sessions'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=IN_PROGRESS)

    # Personal details
    national_id = models.CharField(max_length=50, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    profile_photo = models.ImageField(
        upload_to='onboarding/photos/%Y/%m/',
        null=True,
        blank=True
    )

    # Emergency contact
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True)

    # Next of kin
    next_of_kin_name = models.CharField(max_length=150, blank=True)
    next_of_kin_phone = models.CharField(max_length=20, blank=True)
    next_of_kin_relationship = models.CharField(max_length=50, blank=True)

    # Dependants
    has_dependants = models.BooleanField(default=False)
    dependants_details = models.JSONField(default=list, blank=True)

    # Payment details
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_number = models.CharField(max_length=50, blank=True)
    mobile_money_number = models.CharField(max_length=20, blank=True)

    # Employment details
    employment_type = models.CharField(
        max_length=20,
        choices=[
            ('FULL_TIME', 'Full Time'),
            ('PART_TIME', 'Part Time'),
            ('CONTRACT', 'Contract'),
        ],
        default='FULL_TIME'
    )
    pay_frequency = models.CharField(
        max_length=20,
        choices=[
            ('MONTHLY', 'Monthly'),
            ('BI_WEEKLY', 'Bi-Weekly'),
            ('WEEKLY', 'Weekly'),
        ],
        default='MONTHLY'
    )
    start_date = models.DateField(null=True, blank=True)
    probation_end_date = models.DateField(null=True, blank=True)

    # Documents
    id_document = models.FileField(
        upload_to='onboarding/documents/%Y/%m/',
        null=True,
        blank=True
    )
    additional_documents = models.JSONField(default=list, blank=True)

    # Completion
    completed_at = models.DateTimeField(null=True, blank=True)
    employee = models.OneToOneField(
        'hr.Employee',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='onboarding_record'
    )
    appointment_letter_sent_at = models.DateTimeField(null=True, blank=True)
    portal_credentials_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Onboarding — {self.applicant.full_name} ({self.status})"

    @property
    def is_complete(self):
        return self.status == self.COMPLETED