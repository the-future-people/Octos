from rest_framework import serializers
from apps.hr.models import (
    Employee, PayrollRecord, JobPosition,
    Applicant, StageScore, StageQuestionnaire,
    OnboardingRecord, OfferLetter,
)


# ── Public (careers) serializers ──────────────────────────────────────────────

# CVs and cover letters from the public careers form: PDF or Word, 5 MB max,
# and the file's first bytes must match its extension (a renamed .exe is refused).
DOCUMENT_SIGNATURES = {
    '.pdf' : b'%PDF-',
    '.docx': b'PK\x03\x04',
    '.doc' : b'\xd0\xcf\x11\xe0',
}
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


def validate_public_document(file, label):
    import os
    ext = os.path.splitext(file.name or '')[1].lower()
    if ext not in DOCUMENT_SIGNATURES:
        raise serializers.ValidationError(f'{label} must be a PDF or Word document.')
    if file.size > MAX_DOCUMENT_BYTES:
        raise serializers.ValidationError(f'{label} must be 5 MB or smaller.')
    file.seek(0)
    head = file.read(8)
    file.seek(0)
    if not head.startswith(DOCUMENT_SIGNATURES[ext]):
        raise serializers.ValidationError(f'{label} does not look like a real {ext[1:].upper()} file.')
    return file


class PublicVacancySerializer(serializers.ModelSerializer):
    """
    What anyone on the internet can see. No applicant counts, no base_salary —
    pay is shown only as HR wrote it in pay_text (blank = discussed at interview).
    """
    branch_name  = serializers.CharField(source='branch.name', read_only=True)
    branch_code  = serializers.CharField(source='branch.code', read_only=True)
    role_name    = serializers.CharField(source='role.name', read_only=True)
    team_label   = serializers.CharField(source='get_team_display', read_only=True)
    is_open      = serializers.BooleanField(read_only=True)

    class Meta:
        model  = JobPosition
        fields = [
            'id', 'title', 'branch', 'branch_name', 'branch_code',
            'role', 'role_name', 'team', 'team_label',
            'description', 'responsibilities', 'requirements',
            'pay_text', 'working_hours', 'benefits',
            'positions_available', 'employment_type', 'status',
            'opens_at', 'closes_at', 'is_open',
        ]


class PublicApplicationSerializer(serializers.ModelSerializer):
    """Used by the public /careers/apply/ endpoint."""

    cv = serializers.FileField()   # required on the public form (nullable on the model for HR tracks)

    class Meta:
        model  = Applicant
        fields = [
            'first_name', 'last_name', 'email', 'phone',
            'address', 'date_of_birth', 'gender',
            'preferred_channel',
            'vacancy', 'branch_preference', 'role_interest',
            'cv', 'cover_letter',
        ]

    # preferred_channel: SMS, WhatsApp or email. It only says how HR may reach the
    # applicant; HR does that outside Octos, and applications only arrive through this form.

    def validate_cv(self, value):
        return validate_public_document(value, 'CV')

    def validate_cover_letter(self, value):
        if value:
            validate_public_document(value, 'Cover letter')
        return value

    def validate(self, data):
        """
        One application per person per vacancy, and one open general application.
        "Same person" means the same email or the same phone number, compared in
        international form, so 024… and +23324… match.
        """
        from apps.core.phones import to_international

        email   = (data.get('email') or '').strip().lower()
        phone   = to_international(data.get('phone') or '')
        vacancy = data.get('vacancy')

        if vacancy:
            earlier = Applicant.objects.filter(vacancy=vacancy)
            message = "You've already applied for this role. Our HR team has your application."
        else:
            earlier = Applicant.objects.filter(vacancy__isnull=True).exclude(
                status__in=(Applicant.REJECTED, Applicant.WITHDRAWN, Applicant.DECLINED),
            )
            message = 'You already have a general application with us. Our HR team has it on file.'

        for a in earlier.only('email', 'phone'):
            same_email = email and (a.email or '').strip().lower() == email
            same_phone = phone and to_international(a.phone or '') == phone
            if same_email or same_phone:
                raise serializers.ValidationError(message)
        return data

    def create(self, validated_data):
        validated_data['track']  = Applicant.WEBSITE
        validated_data['status'] = Applicant.RECEIVED
        return super().create(validated_data)


class OnboardingFormSerializer(serializers.ModelSerializer):
    """
    Used by the tokenised /careers/onboarding/<token>/ endpoint.
    Candidate fills this themselves — no auth required.
    """
    requires_guarantor_1 = serializers.BooleanField(read_only=True)
    requires_guarantor_2 = serializers.BooleanField(read_only=True)
    requires_reference   = serializers.BooleanField(read_only=True)

    class Meta:
        model  = OnboardingRecord
        fields = [
            'id', 'status',
            'requires_guarantor_1', 'requires_guarantor_2', 'requires_reference',
            # Identity
            'ghana_card_number', 'ssnit_number', 'date_of_birth', 'gender',
            'address', 'profile_photo', 'ghana_card_scan',
            # Next of kin
            'next_of_kin_name', 'next_of_kin_phone', 'next_of_kin_relationship',
            # Emergency
            'emergency_contact_name', 'emergency_contact_phone',
            'emergency_contact_relationship',
            # Payment
            'bank_name', 'bank_account_number', 'bank_branch', 'mobile_money_number',
            # Guarantor 1
            'guarantor_1_name', 'guarantor_1_phone', 'guarantor_1_address',
            'guarantor_1_employer', 'guarantor_1_relationship', 'guarantor_1_id_number',
            # Guarantor 2
            'guarantor_2_name', 'guarantor_2_phone', 'guarantor_2_address',
            'guarantor_2_employer', 'guarantor_2_relationship', 'guarantor_2_id_number',
            # Reference
            'reference_name', 'reference_phone', 'reference_employer',
            'reference_position', 'reference_relationship',
            # Meta
            'additional_documents', 'submitted_at',
        ]
        read_only_fields = ['status', 'submitted_at']


# ── HR (authenticated) serializers ────────────────────────────────────────────

class JobPositionSerializer(serializers.ModelSerializer):
    branch_name     = serializers.CharField(source='branch.name', read_only=True)
    role_name       = serializers.CharField(source='role.name', read_only=True)
    is_open         = serializers.BooleanField(read_only=True)
    applicant_count = serializers.SerializerMethodField()

    class Meta:
        model  = JobPosition
        fields = [
            'id', 'title', 'branch', 'branch_name', 'role', 'role_name',
            'track', 'team', 'description', 'responsibilities', 'requirements',
            'pay_text', 'working_hours', 'benefits',
            'positions_available', 'employment_type', 'base_salary',
            'status', 'opens_at', 'closes_at', 'is_open',
            'applicant_count',
            'created_by', 'created_at',
        ]
        read_only_fields = ['created_by', 'created_at']

    def get_applicant_count(self, obj):
        return obj.applicants.count()


class StageQuestionnaireSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source='role.name', read_only=True)

    class Meta:
        model  = StageQuestionnaire
        fields = [
            'id', 'role', 'role_name', 'stage', 'question_number',
            'question_text', 'guidance', 'pass_threshold', 'is_active',
        ]


class StageScoreSerializer(serializers.ModelSerializer):
    normalized_score = serializers.FloatField(read_only=True)
    raw_score        = serializers.IntegerField(read_only=True)
    passed           = serializers.BooleanField(read_only=True)
    scored_by_name   = serializers.CharField(source='scored_by.full_name', read_only=True)

    class Meta:
        model  = StageScore
        fields = [
            'id', 'stage', 'scored_by', 'scored_by_name',
            'q1_score', 'q2_score', 'q3_score', 'q4_score', 'q5_score',
            'q1_comment', 'q2_comment', 'q3_comment', 'q4_comment', 'q5_comment',
            'general_comment',
            'interview_scheduled_at', 'interview_conducted_at',
            'interviewer', 'interview_location',
            'raw_score', 'normalized_score', 'passed', 'created_at',
        ]
        read_only_fields = ['scored_by', 'created_at']


class StageScoreCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = StageScore
        fields = [
            'stage',
            'q1_score', 'q2_score', 'q3_score', 'q4_score', 'q5_score',
            'q1_comment', 'q2_comment', 'q3_comment', 'q4_comment', 'q5_comment',
            'general_comment',
            'interview_scheduled_at', 'interview_conducted_at',
            'interviewer', 'interview_location',
        ]

    def validate(self, data):
        for i in range(1, 6):
            score = data.get(f'q{i}_score', 0)
            if not (1 <= score <= 5):
                raise serializers.ValidationError(
                    f'q{i}_score must be between 1 and 5.'
                )
        return data


class ApplicantListSerializer(serializers.ModelSerializer):
    full_name      = serializers.CharField(read_only=True)
    vacancy_title  = serializers.CharField(source='vacancy.title', read_only=True)
    branch_name    = serializers.SerializerMethodField()
    # The HR portal's task lanes need these: a screened applicant who passed waits
    # to be scheduled; one who didn't waits to be rejected or re-scored.
    screening_score  = serializers.SerializerMethodField()
    screening_passed = serializers.SerializerMethodField()
    interview_score  = serializers.SerializerMethodField()
    # Other roles the same person (same email or phone) applied for; filled by the list view
    also_applied     = serializers.SerializerMethodField()

    class Meta:
        model  = Applicant
        fields = [
            'id', 'full_name', 'email', 'phone',
            'vacancy', 'vacancy_title', 'branch_name',
            'track', 'status', 'preferred_channel',
            'is_priority', 'created_at',
            'screening_score', 'screening_passed', 'interview_score',
            'also_applied',
        ]

    def get_also_applied(self, obj):
        return self.context.get('also_applied', {}).get(obj.id, [])

    def _score(self, obj, stage):
        # stage_scores is prefetched by the list view
        return next((s for s in obj.stage_scores.all() if s.stage == stage), None)

    def get_screening_score(self, obj):
        s = self._score(obj, StageQuestionnaire.SCREENING)
        return s.raw_score if s else None

    def get_screening_passed(self, obj):
        s = self._score(obj, StageQuestionnaire.SCREENING)
        return s.passed if s else None

    def get_interview_score(self, obj):
        s = self._score(obj, StageQuestionnaire.INTERVIEW)
        return s.raw_score if s and s.raw_score else None

    def get_branch_name(self, obj):
        if obj.branch_assigned:
            return obj.branch_assigned.name
        if obj.vacancy and obj.vacancy.branch:
            return obj.vacancy.branch.name
        if obj.branch_preference:
            return obj.branch_preference.name
        return None


class ApplicantDetailSerializer(serializers.ModelSerializer):
    full_name      = serializers.CharField(read_only=True)
    vacancy_title  = serializers.CharField(source='vacancy.title', read_only=True)
    branch_name    = serializers.SerializerMethodField()
    role_name      = serializers.SerializerMethodField()
    stage_scores   = StageScoreSerializer(many=True, read_only=True)
    questions      = serializers.SerializerMethodField()

    class Meta:
        model  = Applicant
        fields = [
            'id', 'first_name', 'last_name', 'full_name',
            'email', 'phone', 'address', 'date_of_birth', 'gender',
            'preferred_channel',
            'vacancy', 'vacancy_title', 'branch_name', 'role_name',
            'branch_preference', 'branch_assigned', 'role_interest',
            'track', 'status', 'is_priority',
            'cv', 'cover_letter',
            'recommended_by', 'recommendation_note',
            'appointed_by', 'appointment_note',
            'offer_sent_at', 'offer_accepted', 'offer_responded_at',
            'rejection_reason', 'rejected_at',
            'onboarding_token',
            'onboarding_token_expires_at',
            'assigned_hr',
            'stage_scores', 'questions',
            'created_at', 'updated_at',
        ]

    def get_branch_name(self, obj):
        if obj.branch_assigned:
            return obj.branch_assigned.name
        if obj.vacancy and obj.vacancy.branch:
            return obj.vacancy.branch.name
        if obj.branch_preference:
            return obj.branch_preference.name
        return None

    def get_role_name(self, obj):
        if obj.vacancy:
            return obj.vacancy.role.name
        if obj.role_interest:
            return obj.role_interest.name
        return None

    def get_questions(self, obj):
        """Return the role-specific questions for the current stage."""
        role = obj.vacancy.role if obj.vacancy else obj.role_interest
        stage_map = {
            Applicant.RECEIVED:            StageQuestionnaire.SCREENING,
            Applicant.SCREENING:           StageQuestionnaire.SCREENING,
            Applicant.INTERVIEW_SCHEDULED: StageQuestionnaire.INTERVIEW,
            Applicant.INTERVIEW_DONE:      StageQuestionnaire.INTERVIEW,
            Applicant.FINAL_REVIEW:        StageQuestionnaire.FINAL_REVIEW,
        }
        stage = stage_map.get(obj.status)
        if not stage or not role:
            return []
        qs = StageQuestionnaire.objects.filter(
            stage=stage,
            is_active=True,
        ).filter(
            __import__('django.db.models', fromlist=['Q']).Q(role=role) |
            __import__('django.db.models', fromlist=['Q']).Q(role__isnull=True)
        ).order_by('-role', 'question_number')
        return StageQuestionnaireSerializer(qs, many=True).data


class RecommendSerializer(serializers.Serializer):
    first_name          = serializers.CharField()
    last_name           = serializers.CharField()
    email               = serializers.EmailField()
    phone               = serializers.CharField()
    vacancy             = serializers.PrimaryKeyRelatedField(
        queryset=JobPosition.objects.filter(status=JobPosition.OPEN),
        required=False, allow_null=True,
    )
    role_interest       = serializers.PrimaryKeyRelatedField(
        queryset=__import__('apps.accounts.models', fromlist=['Role']).Role.objects.all(),
        required=False, allow_null=True,
    )
    recommendation_note = serializers.CharField(required=False, allow_blank=True)


class AppointSerializer(serializers.Serializer):
    first_name       = serializers.CharField()
    last_name        = serializers.CharField()
    email            = serializers.EmailField()
    phone            = serializers.CharField()
    vacancy          = serializers.PrimaryKeyRelatedField(
        queryset=JobPosition.objects.all(),
        required=False, allow_null=True,
    )
    role             = serializers.PrimaryKeyRelatedField(
        queryset=__import__('apps.accounts.models', fromlist=['Role']).Role.objects.all(),
    )
    branch           = serializers.PrimaryKeyRelatedField(
        queryset=__import__('apps.organization.models', fromlist=['Branch']).Branch.objects.all(),
    )
    appointment_note = serializers.CharField(required=False, allow_blank=True)


class DecideSerializer(serializers.Serializer):
    decision         = serializers.ChoiceField(choices=['HIRE', 'REJECT'])
    rejection_reason = serializers.CharField(required=False, allow_blank=True)


class VerifyInfoSerializer(serializers.Serializer):
    verification_notes = serializers.CharField(required=False, allow_blank=True)


class IssueOfferSerializer(serializers.Serializer):
    branch           = serializers.PrimaryKeyRelatedField(
        queryset=__import__('apps.organization.models', fromlist=['Branch']).Branch.objects.all(),
    )
    salary_offered   = serializers.DecimalField(max_digits=10, decimal_places=2)
    employment_type  = serializers.ChoiceField(
        choices=['FULL_TIME', 'PART_TIME', 'CONTRACT'],
        default='FULL_TIME',
    )
    pay_frequency    = serializers.ChoiceField(
        choices=['MONTHLY', 'BI_WEEKLY', 'WEEKLY'],
        default='MONTHLY',
    )
    start_date       = serializers.DateField()
    probation_months = serializers.IntegerField(default=3)
    additional_terms = serializers.CharField(required=False, allow_blank=True)


class OfferLetterSerializer(serializers.ModelSerializer):
    applicant_name = serializers.CharField(source='applicant.full_name', read_only=True)
    branch_name    = serializers.CharField(source='branch.name', read_only=True)
    role_name      = serializers.CharField(source='role.name', read_only=True)

    class Meta:
        model  = OfferLetter
        fields = [
            'id', 'applicant', 'applicant_name',
            'branch', 'branch_name', 'role', 'role_name',
            'employment_type', 'salary_offered', 'pay_frequency',
            'start_date', 'probation_months', 'additional_terms',
            'status', 'generated_by', 'generated_at',
            'pdf', 'sent_at', 'sent_via',
            'accepted_at', 'declined_at', 'decline_reason',
        ]
        read_only_fields = ['generated_by', 'generated_at', 'status']


class OnboardingRecordSerializer(serializers.ModelSerializer):
    applicant_name       = serializers.CharField(source='applicant.full_name', read_only=True)
    is_complete          = serializers.BooleanField(read_only=True)
    requires_guarantor_1 = serializers.BooleanField(read_only=True)
    requires_guarantor_2 = serializers.BooleanField(read_only=True)
    requires_reference   = serializers.BooleanField(read_only=True)

    class Meta:
        model  = OnboardingRecord
        fields = [
            'id', 'applicant', 'applicant_name', 'conducted_by', 'status',
            'requires_guarantor_1', 'requires_guarantor_2', 'requires_reference',
            'ghana_card_number', 'ssnit_number', 'date_of_birth', 'gender',
            'address', 'profile_photo', 'ghana_card_scan',
            'next_of_kin_name', 'next_of_kin_phone', 'next_of_kin_relationship',
            'emergency_contact_name', 'emergency_contact_phone',
            'emergency_contact_relationship',
            'bank_name', 'bank_account_number', 'bank_branch', 'mobile_money_number',
            'employment_type', 'pay_frequency', 'start_date', 'probation_end_date',
            'guarantor_1_name', 'guarantor_1_phone', 'guarantor_1_address',
            'guarantor_1_employer', 'guarantor_1_relationship', 'guarantor_1_id_number',
            'guarantor_2_name', 'guarantor_2_phone', 'guarantor_2_address',
            'guarantor_2_employer', 'guarantor_2_relationship', 'guarantor_2_id_number',
            'reference_name', 'reference_phone', 'reference_employer',
            'reference_position', 'reference_relationship',
            'additional_documents',
            'submitted_at', 'verified_at', 'verified_by', 'verification_notes',
            'is_complete', 'completed_at', 'portal_credentials_sent_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'conducted_by', 'status', 'submitted_at',
            'verified_at', 'verified_by', 'completed_at', 'created_at', 'updated_at',
        ]


class EmployeeSerializer(serializers.ModelSerializer):
    full_name   = serializers.CharField(read_only=True)
    email       = serializers.EmailField(source='user.email', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    role_name   = serializers.CharField(source='role.name', read_only=True)

    class Meta:
        model  = Employee
        fields = [
            'id', 'employee_number', 'full_name', 'email',
            'branch', 'branch_name', 'role', 'role_name',
            'employment_type', 'status', 'pay_frequency',
            'date_joined', 'base_salary',
            'phone', 'address',
            'emergency_contact_name', 'emergency_contact_phone',
            'rfid_tag', 'profile_photo',
            'onboarding_completed_at', 'created_at',
        ]


class PayrollRecordSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    net_pay       = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model  = PayrollRecord
        fields = [
            'id', 'employee', 'employee_name',
            'period_start', 'period_end',
            'base_salary', 'bonus', 'deductions', 'net_pay',
            'status', 'payment_method', 'payment_reference',
            'paid_at', 'approved_by', 'notes', 'created_at',
        ]
        read_only_fields = ['net_pay', 'created_at']


class EmploymentDetailsSerializer(serializers.Serializer):
    """
    Validates the Employment Details section of the verify-info endpoint.
    Submitted alongside VerifyInfoSerializer when HR confirms onboarding.
    """
    from apps.accounts.models import Role
    from apps.organization.models import Branch, Region

    role        = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.all(),
    )
    designation = serializers.ChoiceField(
        choices=['MAIN', 'DEPUTY', 'MEMBER'],
        default='MAIN',
    )
    branch = serializers.PrimaryKeyRelatedField(
        queryset=__import__(
            'apps.organization.models', fromlist=['Branch']
        ).Branch.objects.all(),
        required=False,
        allow_null=True,
    )
    region = serializers.PrimaryKeyRelatedField(
        queryset=__import__(
            'apps.organization.models', fromlist=['Region']
        ).Region.objects.all(),
        required=False,
        allow_null=True,
    )
    start_date  = serializers.DateField()
    shadow_days = serializers.IntegerField(default=7, min_value=0, max_value=90)

    # Conflict resolution — only required when a conflict exists
    conflict_user = serializers.PrimaryKeyRelatedField(
        queryset=__import__(
            'apps.accounts.models', fromlist=['CustomUser']
        ).CustomUser.objects.all(),
        required=False,
        allow_null=True,
    )
    conflict_resolution = serializers.ChoiceField(
        choices=['DEACTIVATE', 'REASSIGN', 'ROLE_CHANGE'],
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    conflict_new_branch = serializers.PrimaryKeyRelatedField(
        queryset=__import__(
            'apps.organization.models', fromlist=['Branch']
        ).Branch.objects.all(),
        required=False,
        allow_null=True,
    )
    conflict_new_role = serializers.PrimaryKeyRelatedField(
        queryset=__import__(
            'apps.accounts.models', fromlist=['Role']
        ).Role.objects.all(),
        required=False,
        allow_null=True,
    )
    conflict_new_region = serializers.PrimaryKeyRelatedField(
        queryset=__import__(
            'apps.organization.models', fromlist=['Region']
        ).Region.objects.all(),
        required=False,
        allow_null=True,
    )
    conflict_new_designation = serializers.ChoiceField(
        choices=['MAIN', 'DEPUTY', 'MEMBER'],
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    def validate(self, data):
        role        = data.get('role')
        designation = data.get('designation', 'MAIN')
        branch      = data.get('branch')
        region      = data.get('region')

        # Scope validation — ensure the right unit FK is provided
        if role:
            if role.scope == 'BRANCH' and not branch:
                raise serializers.ValidationError(
                    {'branch': 'Branch is required for this role.'}
                )
            if role.scope == 'REGION' and not region:
                raise serializers.ValidationError(
                    {'region': 'Region is required for this role.'}
                )

        # Conflict resolution completeness
        resolution = data.get('conflict_resolution')
        if resolution == 'REASSIGN' and not data.get('conflict_new_branch'):
            raise serializers.ValidationError(
                {'conflict_new_branch': 'New branch is required for REASSIGN.'}
            )
        if resolution == 'ROLE_CHANGE' and not data.get('conflict_new_role'):
            raise serializers.ValidationError(
                {'conflict_new_role': 'New role is required for ROLE_CHANGE.'}
            )

        return data