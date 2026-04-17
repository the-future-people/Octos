from django.db import models
from django.utils.crypto import get_random_string
from apps.core.models import AuditModel


class JobPosition(AuditModel):
    OPEN    = 'OPEN'
    PAUSED  = 'PAUSED'
    CLOSED  = 'CLOSED'
    FILLED  = 'FILLED'

    STATUS_CHOICES = [
        (OPEN,   'Open'),
        (PAUSED, 'Paused'),
        (CLOSED, 'Closed'),
        (FILLED, 'Filled'),
    ]

    PUBLIC         = 'PUBLIC'
    RECOMMENDATION = 'RECOMMENDATION'
    APPOINTMENT    = 'APPOINTMENT'

    TRACK_CHOICES = [
        (PUBLIC,         'Public Application'),
        (RECOMMENDATION, 'BM Recommendation'),
        (APPOINTMENT,    'CEO Direct Appointment'),
    ]

    title               = models.CharField(max_length=150)
    branch              = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='vacancies',
        null=True,
        blank=True,
    )
    role                = models.ForeignKey(
        'accounts.Role',
        on_delete=models.PROTECT,
        related_name='vacancies',
    )
    track               = models.CharField(max_length=20, choices=TRACK_CHOICES, default=PUBLIC)
    description         = models.TextField(blank=True)
    requirements        = models.TextField(blank=True)
    positions_available = models.PositiveIntegerField(default=1)
    employment_type     = models.CharField(
        max_length=20,
        choices=[
            ('FULL_TIME', 'Full Time'),
            ('PART_TIME', 'Part Time'),
            ('CONTRACT',  'Contract'),
        ],
        default='FULL_TIME',
    )
    base_salary  = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN)
    opens_at     = models.DateField()
    closes_at    = models.DateField()
    created_by   = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='created_vacancies',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        branch = self.branch.name if self.branch else 'General'
        return f"{self.title} - {branch} ({self.status})"

    @property
    def is_open(self):
        from django.utils import timezone
        today = timezone.now().date()
        return self.status == self.OPEN and self.opens_at <= today <= self.closes_at


class Applicant(AuditModel):
    WEBSITE        = 'WEBSITE'
    RECOMMENDATION = 'RECOMMENDATION'
    APPOINTMENT    = 'APPOINTMENT'
    INTERNAL       = 'INTERNAL'

    TRACK_CHOICES = [
        (WEBSITE,        'Public Website'),
        (RECOMMENDATION, 'BM Recommendation'),
        (APPOINTMENT,    'CEO Direct Appointment'),
        (INTERNAL,       'Internal Transfer'),
    ]

    WHATSAPP = 'WHATSAPP'
    SMS      = 'SMS'
    EMAIL    = 'EMAIL'

    CHANNEL_CHOICES = [
        (WHATSAPP, 'WhatsApp'),
        (SMS,      'SMS'),
        (EMAIL,    'Email'),
    ]

    RECEIVED            = 'RECEIVED'
    SCREENING           = 'SCREENING'
    INTERVIEW_SCHEDULED = 'INTERVIEW_SCHEDULED'
    INTERVIEW_DONE      = 'INTERVIEW_DONE'
    FINAL_REVIEW        = 'FINAL_REVIEW'
    HIRED               = 'HIRED'
    REJECTED            = 'REJECTED'
    WITHDRAWN           = 'WITHDRAWN'
    APPOINTED           = 'APPOINTED'
    AWAITING_ACCEPTANCE   = 'AWAITING_ACCEPTANCE'
    ACCEPTED              = 'ACCEPTED'
    DECLINED              = 'DECLINED'
    ONBOARDING            = 'ONBOARDING'
    INFORMATION_SUBMITTED = 'INFORMATION_SUBMITTED'
    INFORMATION_VERIFIED  = 'INFORMATION_VERIFIED'
    OFFER_ISSUED          = 'OFFER_ISSUED'
    ACTIVE                = 'ACTIVE'

    STATUS_CHOICES = [
        (RECEIVED,            'Received'),
        (SCREENING,           'Screening'),
        (INTERVIEW_SCHEDULED, 'Interview Scheduled'),
        (INTERVIEW_DONE,      'Interview Done'),
        (FINAL_REVIEW,        'Final Review'),
        (HIRED,               'Hired'),
        (REJECTED,            'Rejected'),
        (WITHDRAWN,           'Withdrawn'),
        (APPOINTED,           'Appointed'),
        (AWAITING_ACCEPTANCE,   'Awaiting Acceptance'),
        (ACCEPTED,              'Accepted'),
        (DECLINED,              'Declined'),
        (ONBOARDING,            'Onboarding'),
        (INFORMATION_SUBMITTED, 'Information Submitted'),
        (INFORMATION_VERIFIED,  'Information Verified'),
        (OFFER_ISSUED,          'Offer Issued'),
        (ACTIVE,                'Active'),
    ]

    first_name    = models.CharField(max_length=100)
    last_name     = models.CharField(max_length=100)
    email         = models.EmailField()
    phone         = models.CharField(max_length=20)
    address       = models.TextField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender        = models.CharField(max_length=20, blank=True)

    preferred_channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default=WHATSAPP)

    vacancy           = models.ForeignKey(
        'hr.JobPosition',
        on_delete=models.PROTECT,
        related_name='applicants',
        null=True,
        blank=True,
    )
    branch_preference = models.ForeignKey(
        'organization.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='preferred_applicants',
    )
    branch_assigned   = models.ForeignKey(
        'organization.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_applicants',
    )
    role_interest     = models.ForeignKey(
        'accounts.Role',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='interested_applicants',
    )

    track  = models.CharField(max_length=20, choices=TRACK_CHOICES, default=WEBSITE)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=RECEIVED)

    cv           = models.FileField(upload_to='recruitment/cvs/%Y/%m/', null=True, blank=True)
    cover_letter = models.FileField(upload_to='recruitment/cover_letters/%Y/%m/', null=True, blank=True)

    recommended_by      = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='recommended_applicants',
    )
    recommendation_note = models.TextField(blank=True)
    is_priority         = models.BooleanField(default=False)

    appointed_by     = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='appointed_applicants',
    )
    appointment_note = models.TextField(blank=True)

    existing_employee = models.ForeignKey(
        'hr.Employee',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='transfer_applications',
    )

    assigned_hr = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_applicants',
    )

    rejection_reason = models.TextField(blank=True)
    rejected_at      = models.DateTimeField(null=True, blank=True)

    onboarding_token            = models.CharField(max_length=64, unique=True, null=True, blank=True)
    onboarding_token_expires_at = models.DateTimeField(null=True, blank=True)

    offer_sent_at      = models.DateTimeField(null=True, blank=True)
    offer_accepted     = models.BooleanField(null=True, blank=True)
    offer_responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-is_priority', '-created_at']

    def __str__(self):
        position = self.vacancy.title if self.vacancy else (self.role_interest.name if self.role_interest else 'General')
        return f"{self.full_name} -> {position} ({self.status})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def generate_onboarding_token(self):
        from django.utils import timezone
        import datetime
        self.onboarding_token = get_random_string(64)
        self.onboarding_token_expires_at = timezone.now() + datetime.timedelta(days=7)
        self.save(update_fields=['onboarding_token', 'onboarding_token_expires_at'])
        return self.onboarding_token

    @property
    def onboarding_token_valid(self):
        from django.utils import timezone
        return (
            self.onboarding_token is not None
            and self.onboarding_token_expires_at is not None
            and self.onboarding_token_expires_at > timezone.now()
        )


class StageQuestionnaire(AuditModel):
    SCREENING    = 'SCREENING'
    INTERVIEW    = 'INTERVIEW'
    FINAL_REVIEW = 'FINAL_REVIEW'

    STAGE_CHOICES = [
        (SCREENING,    'Screening'),
        (INTERVIEW,    'Interview'),
        (FINAL_REVIEW, 'Final Review'),
    ]

    role            = models.ForeignKey(
        'accounts.Role',
        on_delete=models.PROTECT,
        related_name='interview_questions',
        null=True, blank=True,
    )
    stage           = models.CharField(max_length=20, choices=STAGE_CHOICES)
    question_number = models.PositiveSmallIntegerField()
    question_text   = models.TextField()
    guidance        = models.TextField(blank=True)
    pass_threshold  = models.PositiveSmallIntegerField(default=15)
    is_active       = models.BooleanField(default=True)

    class Meta:
        ordering = ['role', 'stage', 'question_number']
        unique_together = [['role', 'stage', 'question_number']]

    def __str__(self):
        role = self.role.name if self.role else 'All Roles'
        return f"{role} - {self.stage} Q{self.question_number}: {self.question_text[:60]}"


class StageScore(AuditModel):
    SCREENING    = 'SCREENING'
    INTERVIEW    = 'INTERVIEW'
    FINAL_REVIEW = 'FINAL_REVIEW'

    STAGE_CHOICES = [
        (SCREENING,    'Screening'),
        (INTERVIEW,    'Interview'),
        (FINAL_REVIEW, 'Final Review'),
    ]

    applicant  = models.ForeignKey(
        'hr.Applicant',
        on_delete=models.CASCADE,
        related_name='stage_scores',
    )
    stage      = models.CharField(max_length=20, choices=STAGE_CHOICES)
    scored_by  = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='scored_applicants',
    )

    q1_score = models.PositiveSmallIntegerField(default=0)
    q2_score = models.PositiveSmallIntegerField(default=0)
    q3_score = models.PositiveSmallIntegerField(default=0)
    q4_score = models.PositiveSmallIntegerField(default=0)
    q5_score = models.PositiveSmallIntegerField(default=0)

    q1_comment = models.TextField(blank=True)
    q2_comment = models.TextField(blank=True)
    q3_comment = models.TextField(blank=True)
    q4_comment = models.TextField(blank=True)
    q5_comment = models.TextField(blank=True)

    general_comment = models.TextField(blank=True)

    interview_scheduled_at = models.DateTimeField(null=True, blank=True)
    interview_conducted_at = models.DateTimeField(null=True, blank=True)
    interviewer            = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='interviews_conducted',
    )
    interview_location = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [['applicant', 'stage']]

    def __str__(self):
        return f"{self.applicant.full_name} - {self.stage} - {self.raw_score}/25"

    @property
    def raw_score(self):
        return self.q1_score + self.q2_score + self.q3_score + self.q4_score + self.q5_score

    @property
    def normalized_score(self):
        return round((self.raw_score / 25) * 10, 2)

    @property
    def passed(self):
        role = None
        if self.applicant.vacancy:
            role = self.applicant.vacancy.role
        elif self.applicant.role_interest:
            role = self.applicant.role_interest

        threshold = 15
        qs = StageQuestionnaire.objects.filter(
            stage=self.stage,
            is_active=True,
        ).filter(
            models.Q(role=role) | models.Q(role__isnull=True)
        ).order_by('-role')

        if qs.exists():
            threshold = qs.first().pass_threshold

        return self.raw_score >= threshold