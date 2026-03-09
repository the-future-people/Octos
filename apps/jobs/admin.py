from django.contrib import admin
from apps.jobs.models import Job, JobFile, Service, PricingRule, PriceOverrideLog


class JobFileInline(admin.TabularInline):
    model = JobFile
    extra = 0
    readonly_fields = ['created_at']


class PriceOverrideInline(admin.TabularInline):
    model = PriceOverrideLog
    extra = 0
    readonly_fields = ['created_at']


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ['job_number', 'title', 'job_type', 'status', 'priority', 'branch', 'assigned_to', 'is_routed', 'estimated_cost', 'final_cost', 'created_at']
    list_filter = ['job_type', 'status', 'priority', 'is_routed', 'branch']
    search_fields = ['job_number', 'title', 'description']
    readonly_fields = ['job_number', 'created_at', 'updated_at']
    inlines = [JobFileInline, PriceOverrideInline]


@admin.register(JobFile)
class JobFileAdmin(admin.ModelAdmin):
    list_display = ['job', 'file_type', 'uploaded_by', 'created_at']
    list_filter = ['file_type']


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'category', 'unit', 'requires_design', 'requires_file_upload', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['name', 'code']


@admin.register(PricingRule)
class PricingRuleAdmin(admin.ModelAdmin):
    list_display = ['service', 'branch', 'base_price', 'color_multiplier', 'is_active']
    list_filter = ['is_active', 'branch', 'service__category']
    search_fields = ['service__name']


@admin.register(PriceOverrideLog)
class PriceOverrideLogAdmin(admin.ModelAdmin):
    list_display = ['job', 'original_price', 'overridden_price', 'authorized_by', 'created_at']
    readonly_fields = ['created_at']