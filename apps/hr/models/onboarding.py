from django.db import models
from apps.core.models import AuditModel


class OnboardingRecord(AuditModel):
    IN_PROGRESS = 'IN_PROGRESS'
    SUBMITTED   = 'SUBMITTED'
    VERIFIED    = 'VERIFIED'
    COMPLETED   = 'COMPLETED'
    CANCELLED   = 'CANCELLED'

    STATUS_CHOICES = [
        (IN_PROGRESS, 'In Progress'),
        (SUBMITTED,   'Submitted - Awaiting HR Review'),
        (VERIFIED,    'Verified - Ready for Offer'),
        (COMPLETED,   'Completed'),
        (CANCELLED,   'Cancelled'),
    ]

    applicant    = models.OneToOneField(
        'hr.Applicant',
        on_delete=models.PROTECT,
        related_name='onboarding',
    )
    conducted_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='onboarding_sessions',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=IN_PROGRESS)

    ghana_card_number = models.CharField(max_length=50, blank=True)
    ssnit_number      = models.CharField(max_length=50, blank=True)
    date_of_birth     = models.DateField(null=True, blank=True)
    gender            = models.CharField(max_length=20, blank=True)
    address           = models.TextField(blank=True)
    profile_photo     = models.ImageField(upload_to='onboarding/photos/%Y/%m/', null=True, blank=True)
    ghana_card_scan   = models.FileField(upload_to='onboarding/documents/%Y/%m/', null=True, blank=True)

    next_of_kin_name         = models.CharField(max_length=150, blank=True)
    next_of_kin_phone        = models.CharField(max_length=20, blank=True)
    next_of_kin_relationship = models.CharField(max_length=50, blank=True)

    emergency_contact_name         = models.CharField(max_length=150, blank=True)
    emergency_contact_phone        = models.CharField(max_length=20, blank=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True)

    bank_name            = models.CharField(max_length=100, blank=True)
    bank_account_number  = models.CharField(max_length=50, blank=True)
    bank_branch          = models.CharField(max_length=100, blank=True)
    mobile_money_number  = models.CharField(max_length=20, blank=True)

    employment_type = models.CharField(
        max_length=20,
        choices=[('FULL_TIME','Full Time'),('PART_TIME','Part Time'),('CONTRACT','Contract')],
        default='FULL_TIME',
    )
    pay_frequency = models.CharField(
        max_length=20,
        choices=[('MONTHLY','Monthly'),('BI_WEEKLY','Bi-Weekly'),('WEEKLY','Weekly')],
        default='MONTHLY',
    )
    start_date         = models.DateField(null=True, blank=True)
    probation_end_date = models.DateField(null=True, blank=True)

    guarantor_1_name         = models.CharField(max_length=150, blank=True)
    guarantor_1_phone        = models.CharField(max_length=20, blank=True)
    guarantor_1_address      = models.TextField(blank=True)
    guarantor_1_employer     = models.CharField(max_length=150, blank=True)
    guarantor_1_relationship = models.CharField(max_length=50, blank=True)
    guarantor_1_id_number    = models.CharField(max_length=50, blank=True)

    guarantor_2_name         = models.CharField(max_length=150, blank=True)
    guarantor_2_phone        = models.CharField(max_length=20, blank=True)
    guarantor_2_address      = models.TextField(blank=True)
    guarantor_2_employer     = models.CharField(max_length=150, blank=True)
    guarantor_2_relationship = models.CharField(max_length=50, blank=True)
    guarantor_2_id_number    = models.CharField(max_length=50, blank=True)

    reference_name         = models.CharField(max_length=150, blank=True)
    reference_phone        = models.CharField(max_length=20, blank=True)
    reference_employer     = models.CharField(max_length=150, blank=True)
    reference_position     = models.CharField(max_length=100, blank=True)
    reference_relationship = models.CharField(max_length=50, blank=True)

    additional_documents = models.JSONField(default=list, blank=True)

    submitted_at       = models.DateTimeField(null=True, blank=True)
    verified_at        = models.DateTimeField(null=True, blank=True)
    verified_by        = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='verified_onboarding_records',
    )
    verification_notes = models.TextField(blank=True)

    completed_at               = models.DateTimeField(null=True, blank=True)
    employee                   = models.OneToOneField(
        'hr.Employee',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='onboarding_record',
    )
    portal_credentials_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Onboarding - {self.applicant.full_name} ({self.status})"

    @property
    def is_complete(self):
        return self.status == self.COMPLETED

    def requires_guarantor_1(self):
        role = self._get_role_name()
        return role in ('CASHIER', 'BRANCH_MANAGER')

    def requires_guarantor_2(self):
        return self._get_role_name() == 'CASHIER'

    def requires_reference(self):
        role = self._get_role_name()
        return role in ('BRANCH_MANAGER', 'BELT_MANAGER', 'REGIONAL_MANAGER')

    def _get_role_name(self):
        try:
            role = self.applicant.vacancy.role if self.applicant.vacancy else self.applicant.role_interest
            return role.name.upper().replace(' ', '_') if role else ''
        except Exception:
            return ''

    def is_form_complete(self):
        errors = []
        required_common = [
            'ghana_card_number', 'ssnit_number', 'date_of_birth',
            'next_of_kin_name', 'next_of_kin_phone',
            'bank_name', 'bank_account_number',
        ]
        for field in required_common:
            if not getattr(self, field):
                errors.append(f'{field} is required')

        if self.requires_guarantor_1():
            for f in ['guarantor_1_name', 'guarantor_1_phone', 'guarantor_1_address',
                      'guarantor_1_employer', 'guarantor_1_relationship']:
                if not getattr(self, f):
                    errors.append(f'{f} is required for this role')

        if self.requires_guarantor_2():
            for f in ['guarantor_2_name', 'guarantor_2_phone', 'guarantor_2_address',
                      'guarantor_2_employer', 'guarantor_2_relationship']:
                if not getattr(self, f):
                    errors.append(f'{f} is required for Cashier role')

        if self.requires_reference():
            for f in ['reference_name', 'reference_phone', 'reference_employer']:
                if not getattr(self, f):
                    errors.append(f'{f} is required for this role')

        return len(errors) == 0, errors


class OfferLetter(AuditModel):
    DRAFT    = 'DRAFT'
    SENT     = 'SENT'
    ACCEPTED = 'ACCEPTED'
    DECLINED = 'DECLINED'

    STATUS_CHOICES = [
        (DRAFT,    'Draft'),
        (SENT,     'Sent'),
        (ACCEPTED, 'Accepted'),
        (DECLINED, 'Declined'),
    ]

    applicant    = models.OneToOneField(
        'hr.Applicant',
        on_delete=models.PROTECT,
        related_name='offer_letter',
    )
    branch       = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='offer_letters',
    )
    role         = models.ForeignKey(
        'accounts.Role',
        on_delete=models.PROTECT,
        related_name='offer_letters',
    )

    employment_type  = models.CharField(max_length=20, default='FULL_TIME')
    salary_offered   = models.DecimalField(max_digits=10, decimal_places=2)
    pay_frequency    = models.CharField(max_length=20, default='MONTHLY')
    start_date       = models.DateField()
    probation_months = models.PositiveSmallIntegerField(default=3)
    additional_terms = models.TextField(blank=True)

    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    generated_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='generated_offer_letters',
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    pdf     = models.FileField(upload_to='recruitment/offer_letters/%Y/%m/', null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_via = models.CharField(max_length=20, blank=True)

    accepted_at    = models.DateTimeField(null=True, blank=True)
    declined_at    = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-generated_at']

    def __str__(self):
        return f"Offer - {self.applicant.full_name} | {self.role.name} @ {self.branch.name} ({self.status})"