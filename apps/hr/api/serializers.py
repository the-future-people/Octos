from rest_framework import serializers
from apps.hr.models import (
    Employee, PayrollRecord, JobPosition,
    Applicant, StageScore, StageQuestionnaire,
    OnboardingRecord, OfferLetter,
)


# ── Public (careers) serializers ──────────────────────────────────────────────
class PublicVacancySerializer(serializers.ModelSerializer):
    branch_name  = serializers.CharField(source='branch.name', read_only=True)
    branch_code  = serializers.CharField(source='branch.code', read_only=True)
    role_name    = serializers.CharField(source='role.name', read_only=True)
    is_open      = serializers.BooleanField(read_only=True)
    applicant_count = serializers.SerializerMethodField()

    class Meta:
        model  = JobPosition
        fields = [
            'id', 'title', 'branch', 'branch_name', 'branch_code',
            'role', 'role_name', 'description', 'requirements',
            'positions_available', 'employment_type', 'status',
            'opens_at', 'closes_at', 'is_open',
            'applicant_count',
        ]

    def get_applicant_count(self, obj):
        return obj.applicants.count()


class PublicApplicationSerializer(serializers.ModelSerializer):
    """Used by the public /careers/apply/ endpoint."""

    class Meta:
        model  = Applicant
        fields = [
            'first_name', 'last_name', 'email', 'phone',
            'address', 'date_of_birth', 'gender',
            'preferred_channel',
            'vacancy', 'branch_preference', 'role_interest',
            'cv', 'cover_letter',
        ]

    def validate(self, data):
        email   = data.get('email')
        vacancy = data.get('vacancy')
        if vacancy and Applicant.objects.filter(email=email, vacancy=vacancy).exists():
            raise serializers.ValidationError(
                'You have already applied for this position.'
            )
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
            'track', 'description', 'requirements',
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

    class Meta:
        model  = Applicant
        fields = [
            'id', 'full_name', 'email', 'phone',
            'vacancy', 'vacancy_title', 'branch_name',
            'track', 'status', 'preferred_channel',
            'is_priority', 'created_at',
        ]

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