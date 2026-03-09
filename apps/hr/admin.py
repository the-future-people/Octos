from django.contrib import admin
from apps.hr.models import (
    Employee, PayrollRecord, JobPosition,
    Applicant, StageScore, StageQuestionnaire, OnboardingRecord
)


class PayrollInline(admin.TabularInline):
    model = PayrollRecord
    extra = 0
    readonly_fields = ['net_pay', 'created_at']


class StageScoreInline(admin.TabularInline):
    model = StageScore
    extra = 0
    readonly_fields = ['normalized_score', 'passed', 'created_at']


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


@admin.register(JobPosition)
class JobPositionAdmin(admin.ModelAdmin):
    list_display = ['title', 'branch', 'role', 'employment_type', 'vacancies', 'status', 'opens_at', 'closes_at']
    list_filter = ['status', 'employment_type', 'branch']
    search_fields = ['title', 'branch__name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Applicant)
class ApplicantAdmin(admin.ModelAdmin):
    list_display = [
        'full_name', 'email', 'phone', 'position',
        'channel', 'stage', 'is_priority', 'created_at'
    ]
    list_filter = ['stage', 'channel', 'is_priority']
    search_fields = ['first_name', 'last_name', 'email', 'phone']
    readonly_fields = ['full_name', 'created_at', 'updated_at']
    inlines = [StageScoreInline]


@admin.register(StageScore)
class StageScoreAdmin(admin.ModelAdmin):
    list_display = ['applicant', 'stage', 'scored_by', 'raw_score', 'normalized_score', 'passed']
    list_filter = ['stage']
    readonly_fields = ['raw_score', 'normalized_score', 'passed', 'created_at']


@admin.register(StageQuestionnaire)
class StageQuestionnaireAdmin(admin.ModelAdmin):
    list_display = ['stage', 'question_number', 'question_text', 'is_active']
    list_filter = ['stage', 'is_active']


@admin.register(OnboardingRecord)
class OnboardingRecordAdmin(admin.ModelAdmin):
    list_display = [
        'applicant', 'conducted_by', 'status',
        'employment_type', 'start_date', 'completed_at'
    ]
    list_filter = ['status', 'employment_type']
    readonly_fields = ['created_at', 'updated_at']