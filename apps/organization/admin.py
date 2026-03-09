from django.contrib import admin
from apps.organization.models import Belt, Region, Branch


@admin.register(Belt)
class BeltAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'code']


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'belt', 'is_active', 'created_at']
    list_filter = ['is_active', 'belt']
    search_fields = ['name', 'code']


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'region', 'is_headquarters', 'is_regional_hq', 'is_active', 'load_percentage']
    list_filter = ['is_active', 'is_headquarters', 'is_regional_hq', 'region__belt']
    search_fields = ['name', 'code']
    readonly_fields = ['load_percentage', 'is_available']