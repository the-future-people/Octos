from django.contrib import admin
from apps.communications.models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ['direction', 'channel', 'message_type', 'status', 'sent_by', 'created_at']
    can_delete = False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = [
        'display_name', 'branch', 'channel', 'status',
        'assigned_to', 'unread_count', 'last_message_at'
    ]
    list_filter = ['channel', 'status', 'branch']
    search_fields = ['contact_phone', 'contact_email', 'contact_name']
    readonly_fields = ['unread_count', 'last_message_at', 'last_message_preview', 'created_at']
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = [
        'conversation', 'direction', 'channel',
        'message_type', 'status', 'sent_by', 'is_internal_note', 'created_at'
    ]
    list_filter = ['direction', 'channel', 'message_type', 'status', 'is_internal_note']
    readonly_fields = ['created_at']