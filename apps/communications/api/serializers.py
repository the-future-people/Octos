from rest_framework import serializers
from apps.communications.models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    sent_by_name = serializers.CharField(source='sent_by.full_name', read_only=True)

    class Meta:
        model = Message
        fields = [
            'id', 'direction', 'channel', 'message_type', 'status',
            'body', 'media_url', 'media_file', 'sent_by', 'sent_by_name',
            'external_id', 'call_duration', 'caller_id',
            'is_internal_note', 'created_at',
        ]
        read_only_fields = ['sent_by', 'direction', 'created_at']


class MessageCreateSerializer(serializers.ModelSerializer):
    # body is required and must not be blank for outbound messages
    body = serializers.CharField(required=True, allow_blank=False)

    class Meta:
        model = Message
        fields = ['body', 'message_type', 'media_file', 'is_internal_note']


class ConversationListSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.CharField(
        source='assigned_to.full_name', read_only=True
    )

    class Meta:
        model = Conversation
        fields = [
            'id', 'display_name', 'branch', 'channel', 'status',
            'assigned_to', 'assigned_to_name',
            'unread_count', 'last_message_at', 'last_message_preview',
            'created_at',
        ]

    def get_display_name(self, obj):
        return obj.display_name


class ConversationDetailSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.CharField(
        source='assigned_to.full_name', read_only=True
    )
    messages = MessageSerializer(many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = [
            'id', 'display_name', 'branch', 'channel', 'status',
            'contact_phone', 'contact_email', 'contact_name',
            'customer', 'assigned_to', 'assigned_to_name',
            'unread_count', 'last_message_at', 'jobs',
            'messages', 'created_at', 'updated_at',
        ]

    def get_display_name(self, obj):
        return obj.display_name


class ConversationAssignSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()