from django import forms
from django.contrib import admin
from django.utils import timezone

from .models import MachineOperator


class MachineOperatorForm(forms.ModelForm):
    class Meta:
        model = MachineOperator
        fields = ['operator', 'machine', 'active_from', 'active_until']

    def clean(self):
        cleaned = super().clean()
        operator, machine = cleaned.get('operator'), cleaned.get('machine')
        # Someone at Westland cannot run a machine at Madina.
        if operator and machine and operator.branch_id != machine.branch_id:
            raise forms.ValidationError(
                f'{operator} works at a different branch from {machine.name}.'
            )
        return cleaned


@admin.register(MachineOperator)
class MachineOperatorAdmin(admin.ModelAdmin):
    """
    Who runs which machine. An assignment is ended, never deleted: who ran
    a machine last month stays answerable. Assigning someone makes the
    machine staffed, and its work then waits for their Start.
    """
    form          = MachineOperatorForm
    list_display  = ('operator', 'machine', 'branch', 'active_from', 'active_until', 'current')
    list_filter   = ('machine__branch', 'machine', ('active_until', admin.EmptyFieldListFilter))
    search_fields = ('operator__email', 'operator__first_name', 'operator__last_name', 'machine__name')
    ordering      = ('machine__name', '-active_from')
    actions       = ['end_assignments']

    @admin.display(description='Branch')
    def branch(self, obj):
        return obj.machine.branch.code

    @admin.display(boolean=True, description='Current')
    def current(self, obj):
        return obj.is_current

    @admin.action(description='End the selected assignments now')
    def end_assignments(self, request, queryset):
        ended = queryset.filter(active_until__isnull=True).update(active_until=timezone.now())
        self.message_user(request, f'{ended} assignment(s) ended.')

    def has_delete_permission(self, request, obj=None):
        return False