from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from apps.accounts.models import CustomUser, Role, Permission, RFIDAccessLog


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['email', 'full_name', 'employee_id', 'branch', 'role', 'is_active', 'is_clocked_in', 'is_approved']
    list_filter = ['is_active', 'is_clocked_in', 'role', 'branch']
    search_fields = ['email', 'first_name', 'last_name', 'employee_id']
    readonly_fields = ['full_name', 'is_approved', 'created_at', 'updated_at']
    ordering = ['first_name', 'last_name']
    filter_horizontal = []

    fieldsets = (
        ('Login', {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'phone', 'photo')}),
        ('Employment', {'fields': ('employee_id', 'branch', 'role', 'approved_at')}),
        ('Access', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_clocked_in', 'last_clock_in')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'password1', 'password2'),
        }),
    )


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'name', 'created_at']
    search_fields = ['name', 'display_name']
    filter_horizontal = ['permissions']


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ['codename', 'description', 'created_at']
    search_fields = ['codename', 'description']


@admin.register(RFIDAccessLog)
class RFIDAccessLogAdmin(admin.ModelAdmin):
    list_display = ['employee', 'branch', 'action', 'card_uid', 'timestamp']
    list_filter = ['action', 'branch']
    search_fields = ['employee__first_name', 'employee__last_name', 'card_uid']
    readonly_fields = ['timestamp']