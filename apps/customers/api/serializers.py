from rest_framework import serializers
from apps.customers.models import CustomerProfile
from apps.customers.models.customer import CustomerEditLog
from apps.finance.models import CreditAccount, CreditPayment


# ── Customer serializers ──────────────────────────────────────────────────────

class CustomerSerializer(serializers.ModelSerializer):
    full_name        = serializers.CharField(read_only=True)
    display_name     = serializers.CharField(read_only=True)
    titled_name      = serializers.CharField(read_only=True)
    title_display    = serializers.CharField(read_only=True)
    lifetime_spend   = serializers.SerializerMethodField()
    preferred_branch_name = serializers.CharField(
        source='preferred_branch.name', read_only=True
    )
    affiliation_name = serializers.CharField(
        source='affiliation.display_name', read_only=True
    )

    class Meta:
        model  = CustomerProfile
        fields = [
            'id',
            'title', 'title_other', 'title_display',
            'first_name', 'last_name', 'full_name', 'display_name', 'titled_name',
            'gender', 'date_of_birth',
            'phone', 'secondary_phone', 'email', 'preferred_contact',
            'company_name', 'address',
            'customer_type', 'institution_subtype',
            'affiliation', 'affiliation_active',
            'affiliation_name',
            'visit_count', 'tier', 'confidence_score',
            'preferred_branch', 'preferred_branch_name',
            'is_priority', 'is_walkin', 'notes', 'created_at',
            'lifetime_spend',
        ]

    def get_lifetime_spend(self, obj):
        from django.db.models import Sum
        result = obj.jobs.filter(status='COMPLETE').aggregate(total=Sum('amount_paid'))
        return result['total'] or 0


class CustomerListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for lists and dropdowns."""
    full_name    = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    titled_name  = serializers.CharField(read_only=True)
    title_display = serializers.CharField(read_only=True)
    preferred_branch_name = serializers.CharField(
        source='preferred_branch.name', read_only=True
    )
    affiliation_name = serializers.CharField(
        source='affiliation.display_name', read_only=True
    )

    class Meta:
        model  = CustomerProfile
        fields = [
            'id', 'title', 'title_display', 'titled_name',
            'full_name', 'display_name', 'phone', 'secondary_phone',
            'gender', 'preferred_contact',
            'company_name', 'customer_type', 'institution_subtype',
            'affiliation', 'affiliation_active',
            'affiliation_name',
            'tier', 'is_priority', 'confidence_score', 'visit_count',
            'preferred_branch', 'preferred_branch_name',
            'created_at',
        ]


class CustomerCreateSerializer(serializers.ModelSerializer):
    """Used for inline creation from NJ modal and customer management."""

    class Meta:
        model  = CustomerProfile
        fields = [
            'title', 'title_other',
            'first_name', 'last_name',
            'gender', 'date_of_birth',
            'phone', 'secondary_phone', 'email', 'preferred_contact',
            'company_name', 'address',
            'customer_type', 'institution_subtype',
            'affiliation', 'affiliation_active',
            'preferred_branch', 'notes',
        ]
        extra_kwargs = {
            'customer_type': {
                'error_messages': {
                    'invalid_choice': 'Customer type must be INDIVIDUAL, CORPORATE, or INSTITUTION.'
                }
            },
            'phone': {'required': True},
            'first_name': {'required': True},
        }

    def validate_phone(self, value):
        import re
        # Strip spaces, dashes, parentheses
        value = re.sub(r'[\s\-().]', '', value.strip())
        # Normalise +233XXXXXXXXX → 0XXXXXXXXX
        if value.startswith('+233'):
            value = '0' + value[4:]
        elif value.startswith('233') and len(value) >= 12:
            value = '0' + value[3:]
        
        # Skip existence check if we're updating an existing customer
        if self.instance:
            return value
            
        if CustomerProfile.objects.filter(phone=value).exists():
            raise serializers.ValidationError(
                'A customer with this phone number already exists.'
            )
        return value

    def validate_customer_type(self, value):
        allowed = ['INDIVIDUAL', 'BUSINESS', 'INSTITUTION']
        if value not in allowed:
            raise serializers.ValidationError(
                f'Customer type must be one of: {", ".join(allowed)}'
            )
        return value

    def validate(self, attrs):
        affiliation   = attrs.get('affiliation')
        customer_type = attrs.get('customer_type', 'INDIVIDUAL')
        if affiliation:
            if customer_type != CustomerProfile.INDIVIDUAL:
                raise serializers.ValidationError(
                    {'affiliation': 'Only individual customers can have an affiliation.'}
                )
            if affiliation.customer_type not in (
                CustomerProfile.BUSINESS, CustomerProfile.INSTITUTION
            ):
                raise serializers.ValidationError(
                    {'affiliation': 'Affiliation must point to a business or institution.'}
                )
        return attrs


# ── Credit Account serializers ────────────────────────────────────────────────

class CreditAccountSerializer(serializers.ModelSerializer):
    customer_name      = serializers.CharField(source='customer.display_name', read_only=True)
    customer_phone     = serializers.CharField(source='customer.phone', read_only=True)
    customer_address   = serializers.CharField(source='customer.address', read_only=True)
    customer_company   = serializers.CharField(source='customer.company_name', read_only=True)
    customer_type      = serializers.CharField(source='customer.customer_type', read_only=True)
    branch_name        = serializers.CharField(source='branch.name', read_only=True)
    nominated_by_name  = serializers.CharField(source='nominated_by.full_name', read_only=True)
    approved_by_name   = serializers.SerializerMethodField()
    available_credit   = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    utilisation_pct    = serializers.FloatField(read_only=True)

    class Meta:
        model  = CreditAccount
        fields = [
            'id', 'customer', 'customer_name', 'customer_phone',
            'customer_address', 'customer_company', 'customer_type',
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
        extra_kwargs = {
            'customer': {'required': True},
            'branch': {'required': True},
            'account_type': {'required': True},
            'credit_limit': {'required': True, 'min_value': 0.01},
            'payment_terms': {'required': True},
        }

    def validate_credit_limit(self, value):
        if value <= 0:
            raise serializers.ValidationError('Credit limit must be greater than zero.')
        if value > 1000000:  # Add maximum limit
            raise serializers.ValidationError('Credit limit cannot exceed GHS 1,000,000.')
        return value

    def validate_account_type(self, value):
        allowed = ['CORPORATE', 'INSTITUTION', 'INDIVIDUAL']
        if value not in allowed:
            raise serializers.ValidationError(
                f'Account type must be one of: {", ".join(allowed)}'
            )
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

    def validate_sheet_id(self, value):
        from apps.finance.models import DailySalesSheet
        if not DailySalesSheet.objects.filter(id=value).exists():
            raise serializers.ValidationError('Invalid sheet ID.')
        return value


# ── Customer Edit Log serializer ──────────────────────────────────────────────

class CustomerEditLogSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(
        source='changed_by.full_name', read_only=True
    )

    class Meta:
        model  = CustomerEditLog
        fields = [
            'id', 'field_name', 'old_value', 'new_value',
            'changed_by_name', 'changed_at',
        ]