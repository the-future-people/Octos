from django.contrib import admin
from apps.jobs.models import Job, JobFile


class JobFileInline(admin.TabularInline):
    model = JobFile
    extra = 0
    readonly_fields = ['created_at']


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ['job_number', 'title', 'job_type', 'status', 'priority', 'branch', 'assigned_to', 'is_routed', 'created_at']
    list_filter = ['job_type', 'status', 'priority', 'is_routed', 'branch']
    search_fields = ['job_number', 'title', 'description']
    readonly_fields = ['job_number', 'created_at', 'updated_at']
    inlines = [JobFileInline]


@admin.register(JobFile)
class JobFileAdmin(admin.ModelAdmin):
    list_display = ['job', 'file_type', 'uploaded_by', 'created_at']
    list_filter = ['file_type']