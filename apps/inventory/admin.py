from django.contrib import admin
from apps.inventory.models import (
    ConsumableCategory,
    ConsumableItem,
    ServiceConsumable,
    BranchStock,
    StockMovement,
    WasteIncident,
    BranchEquipment,
    MaintenanceLog,
)


@admin.register(ConsumableCategory)
class ConsumableCategoryAdmin(admin.ModelAdmin):
    list_display  = ['name', 'description']
    search_fields = ['name']


@admin.register(ConsumableItem)
class ConsumableItemAdmin(admin.ModelAdmin):
    list_display  = ['name', 'category', 'unit_type', 'paper_size', 'reorder_point', 'is_active']
    list_filter   = ['category', 'unit_type', 'paper_size', 'is_active']
    search_fields = ['name']


@admin.register(ServiceConsumable)
class ServiceConsumableAdmin(admin.ModelAdmin):
    list_display  = ['service', 'consumable', 'quantity_per_unit', 'applies_to_color', 'applies_to_bw']
    list_filter   = ['applies_to_color', 'applies_to_bw']
    search_fields = ['service__name', 'consumable__name']


@admin.register(BranchStock)
class BranchStockAdmin(admin.ModelAdmin):
    list_display  = ['branch', 'consumable', 'quantity', 'is_low', 'is_critical']
    list_filter   = ['branch']
    search_fields = ['consumable__name', 'branch__code']


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display  = ['branch', 'consumable', 'movement_type', 'quantity', 'balance_after', 'recorded_by', 'created_at']
    list_filter   = ['branch', 'movement_type']
    search_fields = ['consumable__name', 'branch__code']
    readonly_fields = ['branch', 'consumable', 'movement_type', 'quantity', 'balance_after', 'recorded_by', 'notes']

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WasteIncident)
class WasteIncidentAdmin(admin.ModelAdmin):
    list_display  = ['branch', 'consumable', 'reason', 'quantity', 'reported_by', 'created_at']
    list_filter   = ['branch', 'reason']
    search_fields = ['consumable__name', 'branch__code']
    readonly_fields = ['branch', 'consumable', 'reason', 'quantity', 'reported_by', 'notes']

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BranchEquipment)
class BranchEquipmentAdmin(admin.ModelAdmin):
    list_display  = ['asset_code', 'name', 'branch', 'quantity', 'condition', 'last_serviced', 'next_service_due', 'is_active']
    list_filter   = ['branch', 'condition', 'is_active']
    search_fields = ['name', 'asset_code', 'serial_number']
    readonly_fields = ['asset_code']


@admin.register(MaintenanceLog)
class MaintenanceLogAdmin(admin.ModelAdmin):
    list_display  = ['equipment', 'log_type', 'service_date', 'performed_by', 'cost', 'condition_after', 'logged_by']
    list_filter   = ['log_type', 'condition_after']
    search_fields = ['equipment__asset_code', 'equipment__name', 'performed_by']
    readonly_fields = ['equipment', 'log_type', 'service_date', 'description',
                       'performed_by', 'cost', 'parts_replaced', 'next_due',
                       'condition_after', 'logged_by', 'notes']

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False