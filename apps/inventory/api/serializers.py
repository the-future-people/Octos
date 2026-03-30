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

from apps.inventory.models import BranchEquipment, MaintenanceLog


class MaintenanceLogSerializer(serializers.ModelSerializer):
    logged_by_name = serializers.CharField(source='logged_by.full_name', read_only=True)
    log_type_display      = serializers.CharField(source='get_log_type_display', read_only=True)
    condition_after_display = serializers.CharField(source='get_condition_after_display', read_only=True)

    class Meta:
        model  = MaintenanceLog
        fields = [
            'id', 'equipment', 'log_type', 'log_type_display',
            'service_date', 'description', 'performed_by',
            'cost', 'parts_replaced', 'next_due',
            'condition_after', 'condition_after_display',
            'logged_by_name', 'notes', 'created_at',
        ]


class MaintenanceLogCreateSerializer(serializers.Serializer):
    log_type        = serializers.ChoiceField(choices=MaintenanceLog.LogType.choices)
    service_date    = serializers.DateField()
    description     = serializers.CharField()
    performed_by    = serializers.CharField(max_length=150)
    cost            = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    parts_replaced  = serializers.CharField(required=False, allow_blank=True)
    next_due        = serializers.DateField(required=False, allow_null=True)
    condition_after = serializers.ChoiceField(choices=BranchEquipment.Condition.choices)
    notes           = serializers.CharField(required=False, allow_blank=True)


class BranchEquipmentSerializer(serializers.ModelSerializer):
    condition_display    = serializers.CharField(source='get_condition_display', read_only=True)
    service_status       = serializers.CharField(read_only=True)
    maintenance_count    = serializers.SerializerMethodField()
    last_log             = serializers.SerializerMethodField()

    class Meta:
        model  = BranchEquipment
        fields = [
            'id', 'asset_code', 'name', 'quantity',
            'condition', 'condition_display', 'service_status',
            'serial_number', 'model_number', 'manufacturer',
            'purchase_date', 'purchase_price', 'warranty_expiry',
            'last_serviced', 'next_service_due', 'location',
            'notes', 'is_active', 'maintenance_count', 'last_log',
            'created_at', 'updated_at',
        ]

    def get_maintenance_count(self, obj):
        return obj.maintenance_logs.count()

    def get_last_log(self, obj):
        log = obj.maintenance_logs.first()
        if not log:
            return None
        return {
            'log_type'    : log.log_type,
            'service_date': log.service_date,
            'performed_by': log.performed_by,
        }


class BranchEquipmentCreateSerializer(serializers.Serializer):
    name             = serializers.CharField(max_length=200)
    quantity         = serializers.IntegerField(min_value=1, default=1)
    condition        = serializers.ChoiceField(choices=BranchEquipment.Condition.choices, default='GOOD')
    serial_number    = serializers.CharField(required=False, allow_blank=True)
    model_number     = serializers.CharField(required=False, allow_blank=True)
    manufacturer     = serializers.CharField(required=False, allow_blank=True)
    purchase_date    = serializers.DateField(required=False, allow_null=True)
    purchase_price   = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    warranty_expiry  = serializers.DateField(required=False, allow_null=True)
    location         = serializers.CharField(required=False, allow_blank=True)
    notes            = serializers.CharField(required=False, allow_blank=True)