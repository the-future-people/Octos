from decimal import Decimal
from rest_framework import serializers
from apps.procurement.models import (
    ReplenishmentOrder,
    ReplenishmentLineItem,
    DeliveryDiscrepancy,
    StockReturn,
)


class ReplenishmentLineItemSerializer(serializers.ModelSerializer):
    consumable_name     = serializers.CharField(source='consumable.name', read_only=True)
    consumable_category = serializers.CharField(source='consumable.category.name', read_only=True)
    unit_label          = serializers.CharField(source='consumable.unit_label', read_only=True)
    effective_qty       = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    has_discrepancy     = serializers.BooleanField(read_only=True)

    class Meta:
        model  = ReplenishmentLineItem
        fields = [
            'id',
            'consumable',
            'consumable_name',
            'consumable_category',
            'unit_label',
            'requested_qty',
            'approved_qty',
            'delivered_qty',
            'accepted_qty',
            'effective_qty',
            'unit_cost',
            'line_total',
            'notes',
            'has_discrepancy',
        ]
        read_only_fields = [
            'id', 'consumable_name', 'consumable_category', 'unit_label',
            'effective_qty', 'has_discrepancy', 'line_total',
        ]


class DeliveryDiscrepancySerializer(serializers.ModelSerializer):
    consumable_name = serializers.CharField(
        source='line_item.consumable.name', read_only=True
    )
    resolved_by_name = serializers.CharField(
        source='resolved_by.full_name', read_only=True, default=None
    )

    class Meta:
        model  = DeliveryDiscrepancy
        fields = [
            'id',
            'line_item',
            'consumable_name',
            'delivered_qty',
            'accepted_qty',
            'difference',
            'bm_reason',
            'resolution',
            'resolved_by',
            'resolved_by_name',
            'resolved_at',
            'resolution_notes',
            'created_at',
        ]
        read_only_fields = fields


class StockReturnSerializer(serializers.ModelSerializer):
    consumable_name  = serializers.CharField(source='consumable.name',       read_only=True)
    collected_by_name = serializers.CharField(source='collected_by.full_name', read_only=True)

    class Meta:
        model  = StockReturn
        fields = [
            'id',
            'consumable',
            'consumable_name',
            'quantity',
            'reason',
            'reason_notes',
            'collected_by',
            'collected_by_name',
            'confirmed_by_bm',
            'created_at',
        ]
        read_only_fields = fields


class ReplenishmentOrderListSerializer(serializers.ModelSerializer):
    """Compact serializer for list views — no nested line items."""
    branch_name  = serializers.CharField(source='branch.name',       read_only=True)
    branch_code  = serializers.CharField(source='branch.code',       read_only=True)
    region_name  = serializers.CharField(source='branch.region.name', read_only=True, default=None)
    week_number  = serializers.IntegerField(source='weekly_report.week_number', read_only=True)
    year         = serializers.IntegerField(source='weekly_report.year',        read_only=True)
    line_item_count = serializers.IntegerField(source='line_items.count', read_only=True)

    class Meta:
        model  = ReplenishmentOrder
        fields = [
            'id',
            'order_number',
            'branch',
            'branch_name',
            'branch_code',
            'region_name',
            'week_number',
            'year',
            'status',
            'estimated_total',
            'approved_budget',
            'line_item_count',
            'submitted_to_finance_at',
            'approved_at',
            'dispatched_at',
            'accepted_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class ReplenishmentOrderDetailSerializer(serializers.ModelSerializer):
    """Full detail serializer including all nested data."""
    branch_name  = serializers.CharField(source='branch.name',        read_only=True)
    branch_code  = serializers.CharField(source='branch.code',        read_only=True)
    region_name  = serializers.CharField(source='branch.region.name', read_only=True, default=None)
    week_number  = serializers.IntegerField(source='weekly_report.week_number', read_only=True)
    year         = serializers.IntegerField(source='weekly_report.year',        read_only=True)

    submitted_to_finance_by_name = serializers.CharField(
        source='submitted_to_finance_by.full_name', read_only=True, default=None
    )
    approved_by_name  = serializers.CharField(source='approved_by.full_name',  read_only=True, default=None)
    dispatched_by_name = serializers.CharField(source='dispatched_by.full_name', read_only=True, default=None)
    accepted_by_name  = serializers.CharField(source='accepted_by.full_name',  read_only=True, default=None)

    line_items    = ReplenishmentLineItemSerializer(many=True, read_only=True)
    discrepancies = DeliveryDiscrepancySerializer(many=True, read_only=True)
    stock_returns = StockReturnSerializer(many=True, read_only=True)

    class Meta:
        model  = ReplenishmentOrder
        fields = [
            'id',
            'order_number',
            'branch',
            'branch_name',
            'branch_code',
            'region_name',
            'weekly_report',
            'week_number',
            'year',
            'status',
            'estimated_total',
            'approved_budget',
            'finance_notes',
            'ops_notes',
            'bm_notes',
            'submitted_to_finance_by',
            'submitted_to_finance_by_name',
            'submitted_to_finance_at',
            'approved_by',
            'approved_by_name',
            'approved_at',
            'dispatched_by',
            'dispatched_by_name',
            'dispatched_at',
            'accepted_by',
            'accepted_by_name',
            'accepted_at',
            'line_items',
            'discrepancies',
            'stock_returns',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


# ── Action request serializers ────────────────────────────────────────────────

class SubmitToFinanceSerializer(serializers.Serializer):
    ops_notes = serializers.CharField(allow_blank=True, default='')


class ApproveOrderSerializer(serializers.Serializer):
    approved_budget  = serializers.DecimalField(max_digits=12, decimal_places=2)
    finance_notes    = serializers.CharField(allow_blank=True, default='')
    line_adjustments = serializers.DictField(
        child    = serializers.DecimalField(max_digits=10, decimal_places=2),
        required = False,
        default  = dict,
    )

    def validate_approved_budget(self, value):
        if value <= Decimal('0'):
            raise serializers.ValidationError("Approved budget must be positive.")
        return value


class RejectOrderSerializer(serializers.Serializer):
    finance_notes = serializers.CharField(min_length=10)


class DispatchOrderSerializer(serializers.Serializer):
    ops_notes = serializers.CharField(allow_blank=True, default='')


class RecordDeliverySerializer(serializers.Serializer):
    """
    delivered_quantities: {line_item_id: qty}
    """
    delivered_quantities = serializers.DictField(
        child = serializers.DecimalField(max_digits=10, decimal_places=2),
    )

    def validate_delivered_quantities(self, value):
        if not value:
            raise serializers.ValidationError("At least one line item quantity is required.")
        for k, v in value.items():
            if not str(k).isdigit():
                raise serializers.ValidationError(f"Invalid line item id: {k}")
            if v < Decimal('0'):
                raise serializers.ValidationError(f"Quantity cannot be negative for line {k}.")
        return value


class StockReturnInputSerializer(serializers.Serializer):
    consumable_id = serializers.IntegerField()
    quantity      = serializers.DecimalField(max_digits=10, decimal_places=2)
    reason        = serializers.ChoiceField(choices=StockReturn.Reason.choices)
    reason_notes  = serializers.CharField(allow_blank=True, default='')


class AcceptDeliverySerializer(serializers.Serializer):
    """
    accepted_quantities: {line_item_id: qty}
    returns: optional list of returned items
    """
    accepted_quantities = serializers.DictField(
        child = serializers.DecimalField(max_digits=10, decimal_places=2),
    )
    bm_notes = serializers.CharField(allow_blank=True, default='')
    returns  = StockReturnInputSerializer(many=True, required=False, default=list)

    def validate_accepted_quantities(self, value):
        if not value:
            raise serializers.ValidationError("At least one accepted quantity is required.")
        for k, v in value.items():
            if not str(k).isdigit():
                raise serializers.ValidationError(f"Invalid line item id: {k}")
            if v < Decimal('0'):
                raise serializers.ValidationError(f"Quantity cannot be negative for line {k}.")
        return value


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5)


class GenerateOrderSerializer(serializers.Serializer):
    weekly_report_id = serializers.IntegerField()


class PrepareDeliverablesSerializer(serializers.Serializer):
    branch_id = serializers.IntegerField()


class BranchDeliveryStatusSerializer(serializers.Serializer):
    """Read-only summary of a branch's delivery health for the ops portal."""
    branch_id       = serializers.IntegerField(source='branch.id')
    branch_name     = serializers.CharField(source='branch.name')
    branch_code     = serializers.CharField(source='branch.code')
    region_name     = serializers.CharField(source='branch.region.name', default=None)
    low_stock_count = serializers.IntegerField()
    low_stock_items = serializers.ListField(child=serializers.CharField())
    can_prepare     = serializers.BooleanField()
    active_order_id     = serializers.SerializerMethodField()
    active_order_number = serializers.SerializerMethodField()
    active_order_status = serializers.SerializerMethodField()
    latest_week         = serializers.SerializerMethodField()
    latest_year         = serializers.SerializerMethodField()
    latest_period       = serializers.SerializerMethodField()

    def get_active_order_id(self, obj):
        return obj['active_order'].pk if obj['active_order'] else None

    def get_active_order_number(self, obj):
        return obj['active_order'].order_number if obj['active_order'] else None

    def get_active_order_status(self, obj):
        return obj['active_order'].status if obj['active_order'] else None

    def get_latest_week(self, obj):
        return obj['latest_report'].week_number if obj['latest_report'] else None

    def get_latest_year(self, obj):
        return obj['latest_report'].year if obj['latest_report'] else None

    def get_latest_period(self, obj):
        if not obj['latest_report']:
            return None
        r = obj['latest_report']
        return f"{r.date_from} → {r.date_to}" if hasattr(r, 'date_from') else f"Week {r.week_number}, {r.year}"


class ReplenishmentLineItemDetailSerializer(serializers.ModelSerializer):
    """
    Extended line item serializer including pack delivery information.
    Used in the ops delivery manifest view.
    """
    consumable_name     = serializers.CharField(source='consumable.name',          read_only=True)
    consumable_category = serializers.CharField(source='consumable.category.name', read_only=True)
    unit_label          = serializers.CharField(source='consumable.unit_label',    read_only=True)
    effective_qty       = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    has_discrepancy     = serializers.BooleanField(read_only=True)

    # Pack delivery info
    pack_size       = serializers.SerializerMethodField()
    pack_label      = serializers.SerializerMethodField()
    packs_requested = serializers.SerializerMethodField()
    pack_description = serializers.SerializerMethodField()

    class Meta:
        model  = ReplenishmentLineItem
        fields = [
            'id',
            'consumable',
            'consumable_name',
            'consumable_category',
            'unit_label',
            'requested_qty',
            'approved_qty',
            'delivered_qty',
            'accepted_qty',
            'effective_qty',
            'unit_cost',
            'line_total',
            'notes',
            'has_discrepancy',
            'pack_size',
            'pack_label',
            'packs_requested',
            'pack_description',
        ]
        read_only_fields = fields

    def get_pack_size(self, obj):
        try:
            return float(obj.consumable.delivery_unit.pack_size)
        except Exception:
            return None

    def get_pack_label(self, obj):
        try:
            return obj.consumable.delivery_unit.pack_label
        except Exception:
            return None

    def get_packs_requested(self, obj):
        try:
            du  = obj.consumable.delivery_unit
            qty = obj.approved_qty or obj.requested_qty
            if du.pack_size and du.pack_size > 0:
                from math import ceil
                return ceil(float(qty) / float(du.pack_size))
        except Exception:
            pass
        return None

    def get_pack_description(self, obj):
        try:
            du = obj.consumable.delivery_unit
            qty = obj.approved_qty or obj.requested_qty
            if du.pack_size and du.pack_size > 0:
                from math import ceil
                packs = ceil(float(qty) / float(du.pack_size))
                return f"{packs} {du.pack_label}(s) × {int(du.pack_size)} {obj.consumable.unit_label}"
        except Exception:
            pass
        return None