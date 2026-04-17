from django.contrib import admin
from apps.hr.models import (
    Employee, PayrollRecord, JobPosition,
    Applicant, StageScore, StageQuestionnaire,
    OnboardingRecord, OfferLetter,
)
from apps.hr.models import EmployeeShift, ShiftOverride, EmployeeShiftSwap


class PayrollInline(admin.TabularInline):
    model = PayrollRecord
    extra = 0
    readonly_fields = ['net_pay', 'created_at']


class StageScoreInline(admin.TabularInline):
    model = StageScore
    extra = 0
    readonly_fields = ['raw_score', 'normalized_score', 'passed', 'created_at']


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display    = ['employee_number', 'full_name', 'branch', 'role',
                       'employment_type', 'status', 'pay_frequency', 'date_joined']
    list_filter     = ['status', 'employment_type', 'pay_frequency', 'branch', 'role']
    search_fields   = ['employee_number', 'user__first_name', 'user__last_name', 'user__email']
    readonly_fields = ['employee_number', 'full_name', 'created_at', 'updated_at']
    inlines         = [PayrollInline]


@admin.register(PayrollRecord)
class PayrollRecordAdmin(admin.ModelAdmin):
    list_display    = ['employee', 'period_start', 'period_end',
                       'base_salary', 'bonus', 'deductions', 'net_pay',
                       'status', 'payment_method', 'paid_at']
    list_filter     = ['status', 'payment_method']
    readonly_fields = ['net_pay', 'created_at', 'updated_at']


@admin.register(JobPosition)
class JobPositionAdmin(admin.ModelAdmin):
    list_display    = ['title', 'branch', 'role', 'track',
                       'positions_available', 'status', 'opens_at', 'closes_at']
    list_filter     = ['status', 'track', 'employment_type', 'branch']
    search_fields   = ['title', 'branch__name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Applicant)
class ApplicantAdmin(admin.ModelAdmin):
    list_display    = ['full_name', 'email', 'phone', 'track',
                       'preferred_channel', 'status', 'is_priority', 'created_at']
    list_filter     = ['status', 'track', 'preferred_channel', 'is_priority']
    search_fields   = ['first_name', 'last_name', 'email', 'phone']
    readonly_fields = ['full_name', 'created_at', 'updated_at']
    inlines         = [StageScoreInline]


@admin.register(StageScore)
class StageScoreAdmin(admin.ModelAdmin):
    list_display    = ['applicant', 'stage', 'scored_by', 'raw_score', 'normalized_score', 'passed']
    list_filter     = ['stage']
    readonly_fields = ['raw_score', 'normalized_score', 'passed', 'created_at']


@admin.register(StageQuestionnaire)
class StageQuestionnaireAdmin(admin.ModelAdmin):
    list_display = ['role', 'stage', 'question_number', 'question_text', 'pass_threshold', 'is_active']
    list_filter  = ['stage', 'role', 'is_active']


@admin.register(OnboardingRecord)
class OnboardingRecordAdmin(admin.ModelAdmin):
    list_display    = ['applicant', 'conducted_by', 'status',
                       'employment_type', 'start_date', 'verified_at', 'completed_at']
    list_filter     = ['status', 'employment_type']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(OfferLetter)
class OfferLetterAdmin(admin.ModelAdmin):
    list_display    = ['applicant', 'role', 'branch', 'salary_offered',
                       'start_date', 'status', 'generated_at', 'sent_at']
    list_filter     = ['status', 'branch', 'role']
    readonly_fields = ['generated_at', 'created_at', 'updated_at']


class ShiftOverrideInline(admin.TabularInline):
    model        = ShiftOverride
    extra        = 0
    readonly_fields = ['created_at']
    fields       = ['date', 'override_type', 'override_start', 'override_end', 'swap_ref', 'notes']


@admin.register(EmployeeShift)
class EmployeeShiftAdmin(admin.ModelAdmin):
    list_display  = ['employee', 'branch', 'get_day', 'start_time', 'end_time', 'is_active']
    list_filter   = ['branch', 'day_of_week', 'is_active']
    search_fields = ['employee__user__first_name', 'employee__user__last_name']

    def get_day(self, obj):
        return obj.get_day_of_week_display()
    get_day.short_description = 'Day'


@admin.register(ShiftOverride)
class ShiftOverrideAdmin(admin.ModelAdmin):
    list_display    = ['employee', 'date', 'override_type', 'override_start', 'override_end', 'swap_ref']
    list_filter     = ['override_type', 'date']
    search_fields   = ['employee__user__first_name', 'employee__user__last_name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(EmployeeShiftSwap)
class EmployeeShiftSwapAdmin(admin.ModelAdmin):
    list_display    = ['initiated_by', 'accepted_by', 'status',
                       'initiator_date', 'compensation_date', 'approved_by', 'approved_at']
    list_filter     = ['status']
    search_fields   = ['initiated_by__user__first_name', 'initiated_by__user__last_name',
                       'accepted_by__user__first_name',  'accepted_by__user__last_name']
    readonly_fields = ['approved_at', 'accepted_at', 'created_at', 'updated_at']