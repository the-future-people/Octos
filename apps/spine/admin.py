from django.contrib import admin

from apps.spine.models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    """Read-only: events can be looked at, never changed."""
    list_display = ('occurred_at', 'kind', 'actor', 'actor_user', 'customer', 'conversation', 'job', 'reason')
    list_filter = ('kind', 'actor')
    search_fields = ('kind', 'reason', 'idempotency_key')
    date_hierarchy = 'occurred_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
