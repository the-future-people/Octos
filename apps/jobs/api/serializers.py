from rest_framework import serializers
from apps.jobs.models import Job, JobFile, Service, PricingRule, JobStatusLog
from apps.jobs.pricing_engine import PricingEngine


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = [
            'id', 'name', 'code', 'category', 'unit',
            'description', 'requires_design', 'requires_file_upload', 'is_active'
        ]


class PricingRuleSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = PricingRule
        fields = [
            'id', 'service', 'service_name', 'branch', 'branch_name',
            'base_price', 'color_multiplier', 'is_active'
        ]


class JobFileSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(
        source='uploaded_by.get_full_name', read_only=True
    )

    class Meta:
        model = JobFile
        fields = ['id', 'file', 'file_type', 'uploaded_by', 'uploaded_by_name', 'notes', 'created_at']


class JobStatusLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source='actor.get_full_name', read_only=True)

    class Meta:
        model = JobStatusLog
        fields = ['id', 'from_status', 'to_status', 'actor', 'actor_name', 'notes', 'transitioned_at']


class JobListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for job lists."""
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.name', read_only=True)

    class Meta:
        model = Job
        fields = [
            'id', 'job_number', 'title', 'job_type', 'status',
            'priority', 'branch', 'branch_name', 'assigned_to',
            'assigned_to_name', 'is_routed', 'estimated_cost', 'created_at'
        ]


class JobDetailSerializer(serializers.ModelSerializer):
    """Full serializer with nested relations."""
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.name', read_only=True)
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    intake_by_name = serializers.CharField(source='intake_by.get_full_name', read_only=True)
    files = JobFileSerializer(many=True, read_only=True)
    status_logs = JobStatusLogSerializer(many=True, read_only=True)
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            'id', 'job_number', 'title', 'job_type', 'status', 'priority',
            'branch', 'branch_name', 'assigned_to', 'assigned_to_name',
            'customer', 'customer_name', 'intake_by', 'intake_by_name',
            'description', 'specifications', 'intake_channel',
            'estimated_time', 'estimated_cost', 'final_cost', 'deadline',
            'is_routed', 'routing_reason', 'notes',
            'files', 'status_logs', 'allowed_transitions',
            'created_at', 'updated_at'
        ]

    def get_allowed_transitions(self, obj):
        from apps.jobs.status_engine import JobStatusEngine
        engine = JobStatusEngine(obj)
        return engine.get_allowed_transitions()


class JobCreateSerializer(serializers.ModelSerializer):
    """Used when creating a new job. Auto-calculates price."""
    quantity = serializers.IntegerField(write_only=True, default=1)
    pages = serializers.IntegerField(write_only=True, default=1)
    is_color = serializers.BooleanField(write_only=True, default=False)
    service = serializers.PrimaryKeyRelatedField(
        queryset=__import__('apps.jobs.models', fromlist=['Service']).Service.objects.all(),
        write_only=True
    )

    class Meta:
        model = Job
        fields = [
            'title', 'job_type', 'priority', 'branch',
            'customer', 'description', 'specifications',
            'intake_channel', 'deadline', 'notes',
            'service', 'quantity', 'pages', 'is_color'
        ]

    def create(self, validated_data):
        service = validated_data.pop('service')
        quantity = validated_data.pop('quantity', 1)
        pages = validated_data.pop('pages', 1)
        is_color = validated_data.pop('is_color', False)

        # Auto-calculate price
        pricing = PricingEngine.get_price(
            service=service,
            branch=validated_data['branch'],
            quantity=quantity,
            is_color=is_color,
            pages=pages
        )

        if pricing['success']:
            validated_data['estimated_cost'] = pricing['total']

        validated_data['intake_by'] = self.context['request'].user
        return Job.objects.create(**validated_data)


class JobTransitionSerializer(serializers.Serializer):
    """Used to transition a job to a new status."""
    to_status = serializers.CharField()
    notes = serializers.CharField(required=False, allow_blank=True)


class JobRouteSerializer(serializers.Serializer):
    """Used to confirm routing a job to another branch."""
    branch_id = serializers.IntegerField()
    notes = serializers.CharField(required=False, allow_blank=True)