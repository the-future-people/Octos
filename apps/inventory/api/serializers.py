from rest_framework import serializers
from apps.inventory.models import (
    ConsumableCategory, ConsumableItem,
    BranchStock, StockMovement, WasteIncident,
)


class ConsumableItemSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model  = ConsumableItem
        fields = [
            'id', 'category', 'name', 'paper_size',
            'unit_type', 'unit_label',
            'reorder_point', 'reorder_qty', 'is_active',
        ]


class BranchStockSerializer(serializers.ModelSerializer):
    name         = serializers.CharField(source='consumable.name',       read_only=True)
    category     = serializers.CharField(source='consumable.category.name', read_only=True)
    paper_size   = serializers.CharField(source='consumable.paper_size', read_only=True)
    unit_type    = serializers.CharField(source='consumable.unit_type',  read_only=True)
    unit_label   = serializers.CharField(source='consumable.unit_label', read_only=True)
    reorder_point = serializers.IntegerField(source='consumable.reorder_point', read_only=True)
    is_low       = serializers.BooleanField(read_only=True)
    is_critical  = serializers.BooleanField(read_only=True)

    class Meta:
        model  = BranchStock
        fields = [
            'id', 'consumable', 'name', 'category',
            'paper_size', 'unit_type', 'unit_label',
            'quantity', 'reorder_point', 'is_low', 'is_critical',
            'updated_at',
        ]


class StockMovementSerializer(serializers.ModelSerializer):
    consumable_name = serializers.CharField(source='consumable.name',      read_only=True)
    recorded_by_name = serializers.CharField(source='recorded_by.full_name', read_only=True)
    job_number      = serializers.SerializerMethodField()

    class Meta:
        model  = StockMovement
        fields = [
            'id', 'consumable', 'consumable_name',
            'movement_type', 'quantity', 'balance_after',
            'reference_job', 'job_number',
            'recorded_by_name', 'notes', 'created_at',
        ]

    def get_job_number(self, obj):
        return obj.reference_job.job_number if obj.reference_job else None


class WasteIncidentSerializer(serializers.ModelSerializer):
    consumable_name  = serializers.CharField(source='consumable.name',        read_only=True)
    reported_by_name = serializers.CharField(source='reported_by.full_name',  read_only=True)
    job_number       = serializers.SerializerMethodField()

    class Meta:
        model  = WasteIncident
        fields = [
            'id', 'consumable', 'consumable_name',
            'quantity', 'reason', 'notes',
            'job', 'job_number',
            'reported_by_name', 'created_at',
        ]

    def get_job_number(self, obj):
        return obj.job.job_number if obj.job else None


class ReceiveStockSerializer(serializers.Serializer):
    consumable_id = serializers.IntegerField()
    quantity      = serializers.DecimalField(max_digits=10, decimal_places=2)
    notes         = serializers.CharField(required=False, allow_blank=True)


class WasteIncidentCreateSerializer(serializers.Serializer):
    consumable_id = serializers.IntegerField()
    quantity      = serializers.DecimalField(max_digits=8, decimal_places=2)
    reason        = serializers.ChoiceField(choices=WasteIncident.Reason.choices)
    job_id        = serializers.IntegerField(required=False, allow_null=True)
    notes         = serializers.CharField(required=False, allow_blank=True)