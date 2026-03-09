from django.contrib import admin
from apps.hr.models import Employee, PayrollRecord


class PayrollInline(admin.TabularInline):
    model = PayrollRecord
    extra = 0
    readonly_fields = ['net_pay', 'created_at']


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = [
        'employee_number', 'full_name', 'branch', 'role',
        'employment_type', 'status', 'pay_frequency', 'date_joined'
    ]
    list_filter = ['status', 'employment_type', 'pay_frequency', 'branch', 'role']
    search_fields = ['employee_number', 'user__first_name', 'user__last_name', 'user__email']
    readonly_fields = ['employee_number', 'full_name', 'created_at', 'updated_at']
    inlines = [PayrollInline]


@admin.register(PayrollRecord)
class PayrollRecordAdmin(admin.ModelAdmin):
    list_display = [
        'employee', 'period_start', 'period_end',
        'base_salary', 'bonus', 'deductions', 'net_pay',
        'status', 'payment_method', 'paid_at'
    ]
    list_filter = ['status', 'payment_method']
    readonly_fields = ['net_pay', 'created_at', 'updated_at']