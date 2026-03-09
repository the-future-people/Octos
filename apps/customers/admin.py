from django.contrib import admin
from apps.customers.models import CustomerProfile


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ['phone', 'full_name', 'email', 'tier', 'visit_count', 'is_priority', 'preferred_branch', 'created_at']
    list_filter = ['tier', 'is_priority', 'preferred_branch']
    search_fields = ['phone', 'first_name', 'last_name', 'email']
    readonly_fields = ['full_name', 'created_at', 'updated_at']