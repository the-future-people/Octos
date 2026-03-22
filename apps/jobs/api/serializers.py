from rest_framework import serializers
from apps.jobs.models import Job, JobFile, JobLineItem, Service, PricingRule, JobStatusLog
from apps.jobs.pricing_engine import PricingEngine


# ─────────────────────────────────────────────────────────────
# Service & Pricing
# ─────────────────────────────────────────────────────────────

class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Service
        fields = [
            'id', 'name', 'code', 'category', 'unit',
            'description', 'requires_design', 'requires_file_upload',
            'is_active', 'spec_template', 'smart_defaults', 'image',
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


# ─────────────────────────────────────────────────────────────
# Job Files
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
# Job Status Log
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
# Job Line Items
# ─────────────────────────────────────────────────────────────

class JobLineItemSerializer(serializers.ModelSerializer):
    """Read serializer — used in job detail responses."""
    service_name = serializers.CharField(source='service.name', read_only=True)
    service_code = serializers.CharField(source='service.code', read_only=True)

    class Meta:
        model  = JobLineItem
        fields = [
            'id', 'service', 'service_name', 'service_code',
            'quantity', 'pages', 'sets', 'is_color',
            'paper_size', 'sides', 'specifications',
            'file_source', 'unit_price', 'line_total',
            'label', 'position',
        ]
        read_only_fields = ['id', 'unit_price', 'line_total', 'label']


class JobLineItemCreateSerializer(serializers.Serializer):
    """
    Write serializer — used when creating a job with line items.
    Accepts one line item's parameters and returns pricing.
    """
    service        = serializers.PrimaryKeyRelatedField(queryset=Service.objects.all())
    quantity       = serializers.IntegerField(default=1, min_value=1)
    pages          = serializers.IntegerField(default=1, min_value=1)
    sets           = serializers.IntegerField(default=1, min_value=1)
    is_color       = serializers.BooleanField(default=False)
    paper_size     = serializers.CharField(default='A4', max_length=10)
    sides          = serializers.ChoiceField(choices=['SINGLE', 'DOUBLE'], default='SINGLE')
    specifications = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        default=dict,
    )
    file_source    = serializers.ChoiceField(
        choices=[c[0] for c in JobLineItem.FILE_SOURCE_CHOICES],
        default=JobLineItem.NA,
    )
    position       = serializers.IntegerField(default=0, min_value=0)


# ─────────────────────────────────────────────────────────────
# Job List & Detail
# ─────────────────────────────────────────────────────────────

class JobListSerializer(serializers.ModelSerializer):
    branch_name      = serializers.CharField(source='branch.name', read_only=True)
    branch_address   = serializers.CharField(source='branch.address', read_only=True)
    branch_phone     = serializers.CharField(source='branch.phone', read_only=True)
    branch_email     = serializers.EmailField(source='branch.email', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.name', read_only=True)
    customer_name    = serializers.SerializerMethodField()
    intake_by_name   = serializers.SerializerMethodField()
    deposit_due      = serializers.SerializerMethodField()
    line_items       = JobLineItemSerializer(many=True, read_only=True)
    line_item_count  = serializers.SerializerMethodField()

    class Meta:
        model  = Job
        fields = [
            'id', 'job_number', 'title', 'job_type', 'status',
            'priority', 'branch', 'branch_name', 'assigned_to',
            'assigned_to_name', 'customer_name', 'intake_by_name',
            'intake_channel', 'is_routed', 'estimated_cost', 'deposit_percentage',
            'amount_paid', 'deposit_due', 'deadline', 'created_at',
            'line_items', 'line_item_count', 'branch_address',
            'branch_phone', 'branch_email',
        ]

    def get_customer_name(self, obj):
        return obj.customer.full_name if obj.customer else None

    def get_intake_by_name(self, obj):
        return obj.intake_by.full_name if obj.intake_by else None

    def get_deposit_due(self, obj):
        if obj.estimated_cost is None:
            return None
        return str((obj.estimated_cost * obj.deposit_percentage) / 100)

    def get_line_item_count(self, obj):
        return obj.line_items.count()


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
    line_items          = JobLineItemSerializer(many=True, read_only=True)
    computed_total      = serializers.SerializerMethodField()

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
            'line_items', 'computed_total',
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

    def get_computed_total(self, obj):
        return str(obj.computed_total)


# ─────────────────────────────────────────────────────────────
# Job Create
# ─────────────────────────────────────────────────────────────

class JobCreateSerializer(serializers.ModelSerializer):
    """
    Create a new job — supports both:
      1. Multi-line-item (new POS-style): pass `line_items` list
      2. Single-service (legacy): pass `service`, `quantity`, `pages`, `is_color`

    Guards enforced at validate():
      - Sunday block — no jobs ever on Sunday
      - Branch lock — no jobs past closing_time (19:25)
      - Must have a sheet — no jobs without an open daily sheet

    For multi-line jobs:
      - title is auto-generated from line items
      - estimated_cost is sum of all line item totals
      - each line item is priced individually via PricingEngine

    For single-service jobs (Production/Design):
      - title defaults to service name
      - estimated_cost calculated from single service params
    """

    # ── Multi-line-item path ──────────────────────────────────
    line_items = JobLineItemCreateSerializer(many=True, required=False)

    # ── Single-service legacy path ────────────────────────────
    service  = serializers.PrimaryKeyRelatedField(
        queryset=Service.objects.all(),
        write_only=True,
        required=False,
    )
    quantity = serializers.IntegerField(write_only=True, default=1, min_value=1, required=False)
    pages    = serializers.IntegerField(write_only=True, default=1, min_value=1, required=False)
    is_color = serializers.BooleanField(write_only=True, default=False, required=False)

    deposit_percentage = serializers.ChoiceField(choices=[70, 100], default=100)

    class Meta:
        model  = Job
        fields = [
            'job_type', 'priority', 'branch',
            'customer', 'description', 'specifications',
            'intake_channel', 'deadline', 'notes',
            # single-service
            'service', 'quantity', 'pages', 'is_color',
            # multi-line
            'line_items',
            'deposit_percentage',
        ]
        extra_kwargs = {
            'branch': {'required': False},
        }

    def validate(self, attrs):
        from django.utils import timezone
        from apps.finance.sheet_engine import SheetEngine

        # ── Branch — default to user's branch ─────────────────
        request = self.context.get('request')
        if not attrs.get('branch') and request and hasattr(request.user, 'branch'):
            attrs['branch'] = request.user.branch
        if not attrs.get('branch'):
            raise serializers.ValidationError({'branch': 'Branch is required.'})

        # ── Sunday block — no jobs ever ────────────────────────
        if timezone.localdate().weekday() == 6:
            raise serializers.ValidationError(
                'Branch is closed on Sundays. No jobs can be recorded.'
            )

        # ── Must have line_items or service ────────────────────
        has_line_items = bool(attrs.get('line_items'))
        has_service    = bool(attrs.get('service'))
        if not has_line_items and not has_service:
            raise serializers.ValidationError(
                'Provide either line_items (multi-service) or service (single-service).'
            )

        # ── Branch lock — no jobs past closing time ────────────
        branch = attrs['branch']
        lock   = SheetEngine(branch).get_branch_lock_status()
        if not lock['can_create_jobs']:
            raise serializers.ValidationError(lock['lock_reason'])

        return attrs

    def create(self, validated_data):
        line_items_data = validated_data.pop('line_items', None)
        service         = validated_data.pop('service', None)
        quantity        = validated_data.pop('quantity', 1)
        pages           = validated_data.pop('pages', 1)
        is_color        = validated_data.pop('is_color', False)
        branch          = validated_data['branch']

        # ── Multi-line-item path ──────────────────────────────
        if line_items_data:
            total        = 0
            priced_items = []

            for item_data in line_items_data:
                svc   = item_data['service']
                pg    = item_data.get('pages', 1)
                sets  = item_data.get('sets', 1)
                color = item_data.get('is_color', False)

                pricing    = PricingEngine.get_price(
                    service  = svc,
                    branch   = branch,
                    quantity = sets,
                    is_color = color,
                    pages    = pg,
                )
                unit_price = float(pricing.get('base_price', pricing.get('total', 0))) if pricing['success'] else 0
                line_total = float(pricing['total']) if pricing['success'] else 0
                total     += line_total

                priced_items.append({
                    **item_data,
                    'unit_price': unit_price,
                    'line_total': line_total,
                })

            # Auto-generate title from services
            names = [i['service'].name for i in priced_items]
            if len(names) == 1:
                validated_data['title'] = names[0]
            elif len(names) <= 3:
                validated_data['title'] = ', '.join(names)
            else:
                validated_data['title'] = ', '.join(names[:3]) + f' +{len(names)-3} more'

            validated_data['estimated_cost'] = total

        # ── Single-service legacy path ────────────────────────
        else:
            validated_data['title'] = service.name
            pricing = PricingEngine.get_price(
                service  = service,
                branch   = branch,
                quantity = quantity,
                is_color = is_color,
                pages    = pages,
            )
            if pricing['success']:
                validated_data['estimated_cost'] = pricing['total']
            priced_items = None

        # ── Status ────────────────────────────────────────────
        if validated_data.get('job_type') != 'DESIGN':
            validated_data['status'] = Job.PENDING_PAYMENT

        # ── Daily sheet ───────────────────────────────────────
        from apps.finance.sheet_engine import SheetEngine
        engine   = SheetEngine(branch)
        sheet, _ = engine.get_or_open_today()
        if sheet is None:
            raise serializers.ValidationError(
                'No active sheet for today. Cannot record jobs.'
            )
        validated_data['daily_sheet'] = sheet

        # ── Intake user ───────────────────────────────────────
        validated_data['intake_by'] = self.context['request'].user

        # ── Create job ────────────────────────────────────────
        job = Job.objects.create(**validated_data)

        # ── Record first job opener on sheet ──────────────────
        engine.set_first_job_opener(sheet, validated_data['intake_by'])

        # ── Create line items ─────────────────────────────────
        if priced_items:
            for i, item_data in enumerate(priced_items):
                item_data['position'] = item_data.get('position', i)
                JobLineItem.objects.create(job=job, **item_data)

        elif service:
            # Single-service — create one line item for consistency
            pricing = PricingEngine.get_price(
                service  = service,
                branch   = branch,
                quantity = quantity,
                is_color = is_color,
                pages    = pages,
            )
            JobLineItem.objects.create(
                job        = job,
                service    = service,
                quantity   = quantity,
                pages      = pages,
                is_color   = is_color,
                unit_price = pricing['base_price'] if pricing['success'] else 0,
                line_total = pricing['total']      if pricing['success'] else 0,
                position   = 0,
            )

        return job


# ─────────────────────────────────────────────────────────────
# Job Transitions & Routing
# ─────────────────────────────────────────────────────────────

class JobTransitionSerializer(serializers.Serializer):
    to_status = serializers.CharField()
    notes     = serializers.CharField(required=False, allow_blank=True)


class JobRouteSerializer(serializers.Serializer):
    branch_id = serializers.IntegerField()
    notes     = serializers.CharField(required=False, allow_blank=True)


# ─────────────────────────────────────────────────────────────
# Cashier Payment
# ─────────────────────────────────────────────────────────────

class CashierPaymentSerializer(serializers.Serializer):
    deposit_percentage = serializers.ChoiceField(choices=[70, 100])
    payment_method     = serializers.ChoiceField(
        choices=['CASH', 'MOMO', 'POS', 'SPLIT'],
        default='CASH',
    )
    momo_reference    = serializers.CharField(required=False, allow_blank=True)
    pos_approval_code = serializers.CharField(required=False, allow_blank=True)
    customer_phone    = serializers.CharField(required=False, allow_blank=True)
    company_name      = serializers.CharField(required=False, allow_blank=True)
    notes             = serializers.CharField(required=False, allow_blank=True)
    cash_tendered     = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    change_given      = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )

    # Split payment legs
    split_legs = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True,
        default=list,
    )

    def validate_momo_reference(self, value):
        if value and not value.isdigit():
            raise serializers.ValidationError(
                'MoMo reference must contain digits only.'
            )
        if value and len(value) != 11:
            raise serializers.ValidationError(
                f'MoMo reference must be exactly 11 digits (got {len(value)}).'
            )
        return value

    def validate_split_legs(self, value):
        if not value:
            return value
        if len(value) != 2:
            raise serializers.ValidationError(
                'Split payment must have exactly 2 legs.'
            )
        for leg in value:
            method = leg.get('method', '')
            amount = leg.get('amount')
            if method not in ['CASH', 'MOMO', 'POS']:
                raise serializers.ValidationError(
                    f'Invalid payment method in split leg: {method}'
                )
            if not amount or float(amount) <= 0:
                raise serializers.ValidationError(
                    'Each split leg must have a positive amount.'
                )
            if method == 'MOMO':
                ref = leg.get('reference', '')
                if not ref:
                    raise serializers.ValidationError(
                        'MoMo leg requires a reference number.'
                    )
                if not ref.isdigit() or len(ref) != 11:
                    raise serializers.ValidationError(
                        f'MoMo reference must be exactly 11 digits (got {len(ref)}).'
                    )
            if method == 'POS':
                code = leg.get('reference', '')
                if not code:
                    raise serializers.ValidationError(
                        'POS leg requires an approval code.'
                    )
        return value

    def validate(self, attrs):
        method = attrs.get('payment_method', 'CASH')

        if method == 'MOMO' and not attrs.get('momo_reference'):
            raise serializers.ValidationError(
                {'momo_reference': 'MoMo reference is required for MoMo payments.'}
            )
        if method == 'POS' and not attrs.get('pos_approval_code'):
            raise serializers.ValidationError(
                {'pos_approval_code': 'POS approval code is required for POS payments.'}
            )
        if method == 'SPLIT' and not attrs.get('split_legs'):
            raise serializers.ValidationError(
                {'split_legs': 'Split legs are required for split payments.'}
            )
        return attrs

# ─────────────────────────────────────────────────────────────
# Service Create
# ─────────────────────────────────────────────────────────────

class ServiceConsumableMappingSerializer(serializers.Serializer):
    """One consumable mapping submitted with a new service."""
    consumable_id      = serializers.IntegerField()
    quantity_per_unit  = serializers.DecimalField(max_digits=8, decimal_places=4, min_value=0.0001)
    applies_to_color   = serializers.BooleanField(default=True)
    applies_to_bw      = serializers.BooleanField(default=True)


class ServiceCreateSerializer(serializers.Serializer):
    name              = serializers.CharField(max_length=100)
    code              = serializers.CharField(max_length=20)
    category          = serializers.ChoiceField(choices=['INSTANT', 'PRODUCTION', 'DESIGN'])
    unit              = serializers.ChoiceField(
        choices=['PER_COPY', 'PER_PIECE', 'PER_SQFT', 'PER_SQCM', 'PER_JOB'],
        default='PER_PIECE',
    )
    description       = serializers.CharField(allow_blank=True, default='')
    base_price        = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    image             = serializers.ImageField(required=False, allow_null=True)
    consumable_mappings = ServiceConsumableMappingSerializer(many=True, required=False, default=list)

    def validate_name(self, value):
        from apps.jobs.models import Service
        if Service.objects.filter(name__iexact=value).exists():
            raise serializers.ValidationError('A service with this name already exists.')
        return value

    def validate_code(self, value):
        from apps.jobs.models import Service
        code = value.upper().replace(' ', '-')
        if Service.objects.filter(code=code).exists():
            raise serializers.ValidationError('A service with this code already exists.')
        return code