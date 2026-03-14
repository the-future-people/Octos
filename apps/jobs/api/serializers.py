from rest_framework import serializers
from apps.jobs.models import Job, JobFile, Service, PricingRule, JobStatusLog
from apps.jobs.pricing_engine import PricingEngine


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Service
        fields = [
            'id', 'name', 'code', 'category', 'unit',
            'description', 'requires_design', 'requires_file_upload',
            'is_active', 'spec_template',
        ]

class PricingRuleSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    branch_name  = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model  = PricingRule
        fields = [
            'id', 'service', 'service_name', 'branch', 'branch_name',
            'base_price', 'color_multiplier', 'is_active',
        ]


class JobFileSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = JobFile
        fields = [
            'id', 'file', 'file_type', 'uploaded_by',
            'uploaded_by_name', 'notes', 'created_at',
        ]
        read_only_fields = ['uploaded_by', 'created_at']

    def get_uploaded_by_name(self, obj):
        return obj.uploaded_by.full_name if obj.uploaded_by else None


class JobFileUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model  = JobFile
        fields = ['file', 'file_type', 'notes']


class JobStatusLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model  = JobStatusLog
        fields = [
            'id', 'from_status', 'to_status',
            'actor', 'actor_name', 'notes', 'transitioned_at',
        ]

    def get_actor_name(self, obj):
        return obj.actor.full_name if obj.actor else None


class JobListSerializer(serializers.ModelSerializer):
    branch_name      = serializers.CharField(source='branch.name', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.name', read_only=True)
    customer_name    = serializers.SerializerMethodField()
    intake_by_name   = serializers.SerializerMethodField()
    deposit_due      = serializers.SerializerMethodField()

    class Meta:
        model  = Job
        fields = [
            'id', 'job_number', 'title', 'job_type', 'status',
            'priority', 'branch', 'branch_name', 'assigned_to',
            'assigned_to_name', 'customer_name', 'intake_by_name',
            'is_routed', 'estimated_cost', 'deposit_percentage',
            'amount_paid', 'deposit_due', 'deadline', 'created_at',
        ]

    def get_customer_name(self, obj):
        return obj.customer.full_name if obj.customer else None

    def get_intake_by_name(self, obj):
        return obj.intake_by.full_name if obj.intake_by else None

    def get_deposit_due(self, obj):
        """Amount the cashier should collect based on deposit_percentage."""
        if obj.estimated_cost is None:
            return None
        return str((obj.estimated_cost * obj.deposit_percentage) / 100)


class JobDetailSerializer(serializers.ModelSerializer):
    branch_name         = serializers.CharField(source='branch.name', read_only=True)
    assigned_to_name    = serializers.CharField(source='assigned_to.name', read_only=True)
    customer_name       = serializers.SerializerMethodField()
    intake_by_name      = serializers.SerializerMethodField()
    files               = JobFileSerializer(many=True, read_only=True)
    status_logs         = JobStatusLogSerializer(many=True, read_only=True)
    allowed_transitions = serializers.SerializerMethodField()
    balance_due         = serializers.SerializerMethodField()
    deposit_due         = serializers.SerializerMethodField()

    class Meta:
        model  = Job
        fields = [
            'id', 'job_number', 'title', 'job_type', 'status', 'priority',
            'branch', 'branch_name', 'assigned_to', 'assigned_to_name',
            'customer', 'customer_name', 'intake_by', 'intake_by_name',
            'description', 'specifications', 'intake_channel',
            'estimated_time', 'estimated_cost', 'final_cost',
            'deposit_percentage', 'amount_paid', 'deposit_due', 'balance_due',
            'deadline', 'is_routed', 'routing_reason', 'notes',
            'files', 'status_logs', 'allowed_transitions',
            'created_at', 'updated_at',
        ]

    def get_customer_name(self, obj):
        return obj.customer.full_name if obj.customer else None

    def get_intake_by_name(self, obj):
        return obj.intake_by.full_name if obj.intake_by else None

    def get_allowed_transitions(self, obj):
        from apps.jobs.status_engine import JobStatusEngine
        request = self.context.get('request')
        actor   = request.user if request else None
        return JobStatusEngine(obj).get_allowed_transitions(actor=actor)

    def get_balance_due(self, obj):
        b = obj.balance_due
        return str(b) if b is not None else None

    def get_deposit_due(self, obj):
        if obj.estimated_cost is None:
            return None
        return str((obj.estimated_cost * obj.deposit_percentage) / 100)


class JobCreateSerializer(serializers.ModelSerializer):
    """
    Create a new job.
    - title is auto-set to the service name (no manual entry needed)
    - Price is auto-calculated from service + branch
    - Branch defaults to requesting user's branch
    """
    quantity           = serializers.IntegerField(write_only=True, default=1, min_value=1)
    pages              = serializers.IntegerField(write_only=True, default=1, min_value=1)
    is_color           = serializers.BooleanField(write_only=True, default=False)
    service            = serializers.PrimaryKeyRelatedField(
        queryset=Service.objects.all(),
        write_only=True,
    )
    deposit_percentage = serializers.ChoiceField(
        choices=[70, 100],
        default=100,
    )

    class Meta:
        model  = Job
        fields = [
            'job_type', 'priority', 'branch',
            'customer', 'description', 'specifications',
            'intake_channel', 'deadline', 'notes',
            'service', 'quantity', 'pages', 'is_color',
            'deposit_percentage',
        ]
        extra_kwargs = {
            'branch': {'required': False},
        }

    def validate(self, attrs):
        request = self.context.get('request')
        if not attrs.get('branch') and request and hasattr(request.user, 'branch'):
            attrs['branch'] = request.user.branch
        if not attrs.get('branch'):
            raise serializers.ValidationError({'branch': 'Branch is required.'})
        return attrs

    def create(self, validated_data):
        service            = validated_data.pop('service')
        quantity           = validated_data.pop('quantity', 1)
        pages              = validated_data.pop('pages', 1)
        is_color           = validated_data.pop('is_color', False)

        # Title is always the service name — no manual entry
        validated_data['title'] = service.name

        pricing = PricingEngine.get_price(
            service  = service,
            branch   = validated_data['branch'],
            quantity = quantity,
            is_color = is_color,
            pages    = pages,
        )
        if pricing['success']:
            validated_data['estimated_cost'] = pricing['total']

        # INSTANT and PRODUCTION go straight to PENDING_PAYMENT.
        # DESIGN stays DRAFT until the brief is submitted.
        if validated_data.get('job_type') != 'DESIGN':
            validated_data['status'] = Job.PENDING_PAYMENT

        validated_data['intake_by'] = self.context['request'].user
        return Job.objects.create(**validated_data)

class JobTransitionSerializer(serializers.Serializer):
    to_status = serializers.CharField()
    notes     = serializers.CharField(required=False, allow_blank=True)


class JobRouteSerializer(serializers.Serializer):
    branch_id = serializers.IntegerField()
    notes     = serializers.CharField(required=False, allow_blank=True)


class CashierPaymentSerializer(serializers.Serializer):
    """
    Used by the cashier to confirm payment.
    deposit_percentage is the only decision the cashier makes — 70% or 100%.
    """
    deposit_percentage = serializers.ChoiceField(choices=[70, 100])
    notes              = serializers.CharField(required=False, allow_blank=True)
