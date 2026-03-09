from django.db import models
from apps.core.models import AuditModel


class Applicant(AuditModel):
    """
    A person who has applied for a position.
    Can apply via public website or branch manager recommendation.
    """

    # Application Channel
    WEBSITE = 'WEBSITE'
    RECOMMENDATION = 'RECOMMENDATION'
    INTERNAL = 'INTERNAL'

    CHANNEL_CHOICES = [
        (WEBSITE, 'Public Website'),
        (RECOMMENDATION, 'Branch Manager Recommendation'),
        (INTERNAL, 'Internal Transfer'),
    ]

    # Pipeline Stage
    APPLICATION_REVIEW = 'APPLICATION_REVIEW'
    SCREENING = 'SCREENING'
    INTERVIEW = 'INTERVIEW'
    FINAL_REVIEW = 'FINAL_REVIEW'
    DECISION = 'DECISION'
    ONBOARDING = 'ONBOARDING'
    HIRED = 'HIRED'
    REJECTED = 'REJECTED'
    WITHDRAWN = 'WITHDRAWN'
    OFFER_DECLINED = 'OFFER_DECLINED'

    STAGE_CHOICES = [
        (APPLICATION_REVIEW, 'Application Review'),
        (SCREENING, 'Screening'),
        (INTERVIEW, 'Interview'),
        (FINAL_REVIEW, 'Final Review'),
        (DECISION, 'Decision'),
        (ONBOARDING, 'Onboarding'),
        (HIRED, 'Hired'),
        (REJECTED, 'Rejected'),
        (WITHDRAWN, 'Withdrawn'),
        (OFFER_DECLINED, 'Offer Declined'),
    ]

    # Personal details
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    address = models.TextField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True)

    # Application details
    position = models.ForeignKey(
        'hr.JobPosition',
        on_delete=models.PROTECT,
        related_name='applicants'
    )
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default=WEBSITE)
    stage = models.CharField(max_length=30, choices=STAGE_CHOICES, default=APPLICATION_REVIEW)
    cv = models.FileField(upload_to='recruitment/cvs/%Y/%m/', null=True, blank=True)
    cover_letter = models.FileField(upload_to='recruitment/cover_letters/%Y/%m/', null=True, blank=True)

    # Recommendation
    recommended_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recommended_applicants'
    )
    recommendation_note = models.TextField(blank=True)
    is_priority = models.BooleanField(default=False)

    # Internal transfer
    existing_employee = models.ForeignKey(
        'hr.Employee',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfer_applications'
    )

    # Offer
    offer_sent_at = models.DateTimeField(null=True, blank=True)
    offer_expires_at = models.DateTimeField(null=True, blank=True)
    offer_accepted = models.BooleanField(null=True, blank=True)
    offer_responded_at = models.DateTimeField(null=True, blank=True)

    # Rejection
    rejection_reason = models.TextField(blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)

    # Assigned HR
    assigned_hr = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_applicants'
    )

    class Meta:
        ordering = ['-is_priority', '-created_at']
        unique_together = [['email', 'position']]

    def __str__(self):
        return f"{self.full_name} → {self.position.title} ({self.stage})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class StageScore(AuditModel):
    """
    Score recorded by HR for an applicant at a specific stage.
    Each stage has 5 questions, each scored 1-5.
    Total = 25 max, normalized to 10 for display.
    Pass threshold = 6.0/10
    """

    SCREENING = 'SCREENING'
    INTERVIEW = 'INTERVIEW'
    FINAL_REVIEW = 'FINAL_REVIEW'

    STAGE_CHOICES = [
        (SCREENING, 'Screening'),
        (INTERVIEW, 'Interview'),
        (FINAL_REVIEW, 'Final Review'),
    ]

    applicant = models.ForeignKey(
        'hr.Applicant',
        on_delete=models.CASCADE,
        related_name='stage_scores'
    )
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES)
    scored_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='scored_applicants'
    )

    # 5 questions, each scored 1-5
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

    # Interview scheduling (only relevant for INTERVIEW stage)
    interview_date = models.DateTimeField(null=True, blank=True)
    interviewer = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='interviews_conducted'
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = [['applicant', 'stage']]

    def __str__(self):
        return f"{self.applicant.full_name} — {self.stage} — {self.normalized_score}/10"

    @property
    def raw_score(self):
        return self.q1_score + self.q2_score + self.q3_score + self.q4_score + self.q5_score

    @property
    def normalized_score(self):
        return round((self.raw_score / 25) * 10, 2)

    @property
    def passed(self):
        return self.normalized_score >= 6.0


class StageQuestionnaire(AuditModel):
    """
    The set of questions used at each stage.
    Questions are company-wide and managed by HQ HR Manager.
    """

    SCREENING = 'SCREENING'
    INTERVIEW = 'INTERVIEW'
    FINAL_REVIEW = 'FINAL_REVIEW'

    STAGE_CHOICES = [
        (SCREENING, 'Screening'),
        (INTERVIEW, 'Interview'),
        (FINAL_REVIEW, 'Final Review'),
    ]

    stage = models.CharField(max_length=20, choices=STAGE_CHOICES)
    question_number = models.PositiveSmallIntegerField()
    question_text = models.TextField()
    guidance = models.TextField(blank=True, help_text='Guidance for HR on what to look for')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['stage', 'question_number']
        unique_together = [['stage', 'question_number']]

    def __str__(self):
        return f"{self.stage} — Q{self.question_number}: {self.question_text[:60]}"