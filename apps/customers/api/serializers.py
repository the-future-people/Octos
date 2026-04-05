from rest_framework import serializers
from apps.customers.models import CustomerProfile
from apps.finance.models import CreditAccount, CreditPayment


# ── Customer serializers ──────────────────────────────────────────────────────

class CustomerSerializer(serializers.ModelSerializer):
    full_name        = serializers.CharField(read_only=True)
    display_name     = serializers.CharField(read_only=True)
    preferred_branch_name = serializers.CharField(
        source='preferred_branch.name', read_only=True
    )

    class Meta:
        model  = CustomerProfile
        fields = [
            'id', 'first_name', 'last_name', 'full_name', 'display_name',
            'phone', 'email', 'company_name', 'address',
            'customer_type', 'institution_subtype',
            'visit_count', 'tier', 'confidence_score',
            'preferred_branch', 'preferred_branch_name',
            'is_priority', 'is_walkin', 'notes', 'created_at',
        ]


class CustomerListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for lists and dropdowns."""
    full_name    = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model  = CustomerProfile
        fields = [
            'id', 'full_name', 'display_name', 'phone',
            'customer_type', 'institution_subtype',
            'tier', 'is_priority', 'confidence_score',
        ]


class CustomerCreateSerializer(serializers.ModelSerializer):
    """Used for inline creation from NJ modal and customer management."""

    class Meta:
        model  = CustomerProfile
        fields = [
            'first_name', 'last_name', 'phone', 'email',
            'company_name', 'address', 'customer_type', 'institution_subtype',
            'preferred_branch', 'notes',
        ]

    def validate_phone(self, value):
        value = value.strip()
        if CustomerProfile.objects.filter(phone=value).exists():
            raise serializers.ValidationError(
                'A customer with this phone number already exists.'
            )
        return value


# ── Credit Account serializers ────────────────────────────────────────────────

class CreditAccountSerializer(serializers.ModelSerializer):
    customer_name      = serializers.CharField(source='customer.display_name', read_only=True)
    customer_phone     = serializers.CharField(source='customer.phone', read_only=True)
    branch_name        = serializers.CharField(source='branch.name', read_only=True)
    nominated_by_name  = serializers.CharField(source='nominated_by.full_name', read_only=True)
    approved_by_name   = serializers.SerializerMethodField()
    available_credit   = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    utilisation_pct    = serializers.FloatField(read_only=True)

    class Meta:
        model  = CreditAccount
        fields = [
            'id', 'customer', 'customer_name', 'customer_phone',
            'branch', 'branch_name',
            'account_type', 'status',
            'credit_limit', 'current_balance', 'available_credit',
            'utilisation_pct', 'payment_terms',
            'organisation_name', 'contact_person',
            'nominated_by', 'nominated_by_name', 'nominated_at',
            'approved_by', 'approved_by_name', 'approved_at',
            'suspension_reason', 'notes', 'created_at',
        ]
        read_only_fields = [
            'current_balance', 'available_credit', 'utilisation_pct',
            'nominated_by', 'nominated_at',
            'approved_by', 'approved_at',
            'created_at',
        ]

    def get_approved_by_name(self, obj):
        return obj.approved_by.full_name if obj.approved_by else None


class CreditAccountNominateSerializer(serializers.ModelSerializer):
    """Used by BM to nominate a customer for a credit account."""

    class Meta:
        model  = CreditAccount
        fields = [
            'customer', 'branch', 'account_type',
            'credit_limit', 'payment_terms',
            'organisation_name', 'contact_person',
            'notes',
        ]

    def validate_credit_limit(self, value):
        if value <= 0:
            raise serializers.ValidationError('Credit limit must be greater than zero.')
        return value

    def validate(self, data):
        # Ensure no active/pending account already exists for this customer+branch
        customer = data.get('customer')
        branch   = data.get('branch')
        if CreditAccount.objects.filter(
            customer=customer,
            branch=branch,
            status__in=['PENDING', 'ACTIVE'],
        ).exists():
            raise serializers.ValidationError(
                'This customer already has an active or pending credit account at this branch.'
            )
        return data


# ── Credit Payment serializers ────────────────────────────────────────────────

class CreditPaymentSerializer(serializers.ModelSerializer):
    customer_name  = serializers.CharField(
        source='credit_account.customer.display_name', read_only=True
    )
    recorded_by_name = serializers.CharField(
        source='received_by.full_name', read_only=True
    )

    class Meta:
        model  = CreditPayment
        fields = [
            'id', 'credit_account', 'customer_name',
            'amount', 'payment_method', 'momo_reference', 'pos_approval_code',
            'balance_before', 'balance_after',
            'recorded_by_name', 'notes', 'created_at',
        ]
        read_only_fields = [
            'balance_before', 'balance_after', 'created_at',
        ]


class CreditSettleSerializer(serializers.Serializer):
    """Used by cashier to record a credit settlement."""
    amount     = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    method     = serializers.ChoiceField(choices=['CASH', 'MOMO', 'POS'])
    reference  = serializers.CharField(max_length=100, required=False, allow_blank=True)
    sheet_id   = serializers.IntegerField()
    notes      = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        method    = data.get('method')
        reference = data.get('reference', '')
        if method == 'MOMO' and not reference:
            raise serializers.ValidationError(
                {'reference': 'MoMo reference number is required.'}
            )
        if method == 'POS' and not reference:
            raise serializers.ValidationError(
                {'reference': 'POS approval code is required.'}
            )
        return data