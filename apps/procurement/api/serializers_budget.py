# apps/procurement/api/serializers_budget.py

from rest_framework import serializers
from apps.procurement.models import AnnualBudget, BudgetEnvelope, Vendor, VendorItem


class BudgetEnvelopeSerializer(serializers.ModelSerializer):
    available       = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    utilisation_pct = serializers.FloatField(read_only=True)
    period_display  = serializers.CharField(source='get_period_display', read_only=True)
    category_display= serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model  = BudgetEnvelope
        fields = [
            'id', 'period_type', 'period', 'period_display',
            'category', 'category_display', 'status',
            'ceiling', 'approved_amount', 'spent',
            'carry_forward', 'available', 'utilisation_pct',
        ]


class AnnualBudgetSerializer(serializers.ModelSerializer):
    proposed_by_name = serializers.CharField(source='proposed_by.full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.full_name', read_only=True)
    envelopes        = BudgetEnvelopeSerializer(many=True, read_only=True)

    class Meta:
        model  = AnnualBudget
        fields = [
            'id', 'year', 'status', 'notes',
            'proposed_by_name', 'approved_by_name', 'approved_at',
            'envelopes',
        ]


class AnnualBudgetCreateSerializer(serializers.Serializer):
    year      = serializers.IntegerField(min_value=2024, max_value=2100)
    notes     = serializers.CharField(required=False, allow_blank=True)
    envelopes = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
    )


class VendorItemSerializer(serializers.ModelSerializer):
    consumable_name = serializers.CharField(source='consumable.name', read_only=True)

    class Meta:
        model  = VendorItem
        fields = [
            'id', 'consumable', 'consumable_name',
            'current_price', 'is_preferred',
            'variance_threshold', 'is_active', 'notes',
        ]


class VendorSerializer(serializers.ModelSerializer):
    items = VendorItemSerializer(many=True, read_only=True)

    class Meta:
        model  = Vendor
        fields = [
            'id', 'name', 'contact', 'phone', 'email',
            'address', 'payment_term', 'is_active', 'notes',
            'items',
        ]