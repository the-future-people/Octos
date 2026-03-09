from rest_framework import serializers
from apps.hr.models import (
    Employee, PayrollRecord, JobPosition,
    Applicant, StageScore, StageQuestionnaire, OnboardingRecord
)
from apps.hr.recruitment_engine import RecruitmentEngine


class JobPositionSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = JobPosition
        fields = [
            'id', 'title', 'branch', 'branch_name', 'role', 'role_name',
            'description', 'requirements', 'vacancies', 'employment_type',
            'base_salary', 'status', 'opens_at', 'closes_at', 'is_open',
            'created_by', 'created_at'
        ]
        read_only_fields = ['created_by', 'created_at']


class StageScoreSerializer(serializers.ModelSerializer):
    normalized_score = serializers.FloatField(read_only=True)
    raw_score = serializers.IntegerField(read_only=True)
    passed = serializers.BooleanField(read_only=True)
    scored_by_name = serializers.CharField(source='scored_by.get_full_name', read_only=True)

    class Meta:
        model = StageScore
        fields = [
            'id', 'stage', 'scored_by', 'scored_by_name',
            'q1_score', 'q2_score', 'q3_score', 'q4_score', 'q5_score',
            'q1_comment', 'q2_comment', 'q3_comment', 'q4_comment', 'q5_comment',
            'general_comment', 'interview_date', 'interviewer',
            'raw_score', 'normalized_score', 'passed', 'created_at'
        ]
        read_only_fields = ['scored_by', 'created_at']


class ApplicantListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    position_title = serializers.CharField(source='position.title', read_only=True)
    branch_name = serializers.CharField(source='position.branch.name', read_only=True)

    class Meta:
        model = Applicant
        fields = [
            'id', 'full_name', 'email', 'phone', 'position',
            'position_title', 'branch_name', 'channel', 'stage',
            'is_priority', 'created_at'
        ]


class ApplicantDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    position_title = serializers.CharField(source='position.title', read_only=True)
    branch_name = serializers.CharField(source='position.branch.name', read_only=True)
    stage_scores = StageScoreSerializer(many=True, read_only=True)
    allowed_transitions = serializers.SerializerMethodField()
    octos_recommendation = serializers.SerializerMethodField()

    class Meta:
        model = Applicant
        fields = [
            'id', 'first_name', 'last_name', 'full_name',
            'email', 'phone', 'address', 'date_of_birth', 'gender',
            'position', 'position_title', 'branch_name',
            'channel', 'stage', 'is_priority',
            'cv', 'cover_letter',
            'recommended_by', 'recommendation_note',
            'offer_sent_at', 'offer_expires_at', 'offer_accepted',
            'rejection_reason', 'assigned_hr',
            'stage_scores', 'allowed_transitions', 'octos_recommendation',
            'created_at', 'updated_at'
        ]

    def get_allowed_transitions(self, obj):
        engine = RecruitmentEngine(obj)
        return engine.get_allowed_transitions()

    def get_octos_recommendation(self, obj):
        engine = RecruitmentEngine(obj)
        return engine.get_octos_recommendation()


class ApplicantCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Applicant
        fields = [
            'first_name', 'last_name', 'email', 'phone',
            'address', 'date_of_birth', 'gender',
            'position', 'channel', 'cv', 'cover_letter',
            'recommended_by', 'recommendation_note'
        ]

    def validate(self, data):
        # Duplicate detection
        email = data.get('email')
        position = data.get('position')
        if Applicant.objects.filter(email=email, position=position).exists():
            raise serializers.ValidationError(
                'This applicant has already applied for this position.'
            )
        return data

    def create(self, validated_data):
        # Auto-flag priority for recommendations
        if validated_data.get('channel') == 'RECOMMENDATION':
            validated_data['is_priority'] = True
        return super().create(validated_data)


class StageTransitionSerializer(serializers.Serializer):
    to_stage = serializers.CharField()
    notes = serializers.CharField(required=False, allow_blank=True)


class StageScoreCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StageScore
        fields = [
            'stage',
            'q1_score', 'q2_score', 'q3_score', 'q4_score', 'q5_score',
            'q1_comment', 'q2_comment', 'q3_comment', 'q4_comment', 'q5_comment',
            'general_comment', 'interview_date', 'interviewer',
        ]

    def validate(self, data):
        for i in range(1, 6):
            score = data.get(f'q{i}_score', 0)
            if not (1 <= score <= 5):
                raise serializers.ValidationError(
                    f'q{i}_score must be between 1 and 5.'
                )
        return data


class OnboardingSerializer(serializers.ModelSerializer):
    applicant_name = serializers.CharField(source='applicant.full_name', read_only=True)
    is_complete = serializers.BooleanField(read_only=True)

    class Meta:
        model = OnboardingRecord
        fields = [
            'id', 'applicant', 'applicant_name', 'conducted_by', 'status',
            'national_id', 'date_of_birth', 'gender', 'address',
            'emergency_contact_name', 'emergency_contact_phone', 'emergency_contact_relationship',
            'next_of_kin_name', 'next_of_kin_phone', 'next_of_kin_relationship',
            'has_dependants', 'dependants_details',
            'bank_name', 'bank_account_number', 'mobile_money_number',
            'employment_type', 'pay_frequency', 'start_date', 'probation_end_date',
            'profile_photo', 'id_document', 'additional_documents',
            'is_complete', 'completed_at',
            'appointment_letter_sent_at', 'portal_credentials_sent_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['conducted_by', 'status', 'completed_at', 'created_at', 'updated_at']


class EmployeeSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)

    class Meta:
        model = Employee
        fields = [
            'id', 'employee_number', 'full_name', 'email',
            'branch', 'branch_name', 'role', 'role_name',
            'employment_type', 'status', 'pay_frequency',
            'date_joined', 'base_salary',
            'phone', 'address', 'national_id',
            'emergency_contact_name', 'emergency_contact_phone',
            'rfid_tag', 'profile_photo',
            'onboarding_completed_at', 'created_at'
        ]


class PayrollRecordSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    net_pay = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = PayrollRecord
        fields = [
            'id', 'employee', 'employee_name',
            'period_start', 'period_end',
            'base_salary', 'bonus', 'deductions', 'net_pay',
            'status', 'payment_method', 'payment_reference',
            'paid_at', 'approved_by', 'notes', 'created_at'
        ]
        read_only_fields = ['net_pay', 'created_at']


class StageQuestionnaireSerializer(serializers.ModelSerializer):
    class Meta:
        model = StageQuestionnaire
        fields = ['id', 'stage', 'question_number', 'question_text', 'guidance', 'is_active']