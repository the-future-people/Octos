from rest_framework import serializers
from apps.communications.models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    sent_by_name = serializers.CharField(source='sent_by.full_name', read_only=True)
    # The message this one quotes, and Octos's report on its own messages (8 Nov 2026).
    reply_preview = serializers.SerializerMethodField()
    report = serializers.SerializerMethodField()

    def get_reply_preview(self, obj):
        q = obj.reply_to
        if q is None:
            return None
        if q.direction == Message.INBOUND:
            who = (q.conversation.contact_name or 'The customer').title()
        elif q.sent_by_id:
            who = q.sent_by.full_name or 'Staff'
        else:
            who = 'Octos'
        return {'id': q.id, 'who': who, 'body': (q.body or '')[:200], 'media_name': q.media_name,
                'media_mime': q.media_mime}

    def get_report(self, obj):
        from apps.communications.services.reports import octos_report
        return octos_report(obj)

    class Meta:
        model = Message
        fields = [
            'id', 'direction', 'channel', 'message_type', 'status', 'error', 'kind',
            'body', 'media_url', 'media_file', 'media_id', 'media_name', 'media_mime',
            'media_size', 'media_pages', 'media_info', 'sent_by', 'sent_by_name',
            'reply_to', 'reply_preview', 'report',
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


def _latest_job(conversation):
    """The newest job linked to a conversation, or None. Uses prefetched jobs when there are any."""
    jobs = list(conversation.jobs.all())
    return max(jobs, key=lambda j: j.created_at) if jobs else None


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
            'handled_by', 'handled_since', 'handoff_reason', 'counter_until',
            'unread_count', 'last_message_at', 'last_message_preview',
            'created_at', 'job',
        ]

    job = serializers.SerializerMethodField()

    def get_job(self, obj):
        """The folder chip: the newest linked job's short reference and what it is."""
        from apps.communications.assistant.tools import _ref
        job = _latest_job(obj)
        if job is None:
            return None
        return {'id': job.pk, 'ref': _ref(job.job_number), 'what': job.line_item_summary}

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
            'handled_by', 'handled_since', 'handoff_reason', 'counter_until',
            'unread_count', 'last_message_at', 'jobs',
            'messages', 'created_at', 'updated_at',
            'job_card', 'window_closes_at',
        ]

    job_card = serializers.SerializerMethodField()
    window_closes_at = serializers.SerializerMethodField()

    def get_job_card(self, obj):
        """
        The newest linked job, described with the same facts Octos tells
        customers (stage in plain words, promise, the cashier's balance),
        so the screen and Octos can never disagree about a job.
        """
        from django.utils import timezone
        from apps.communications.assistant.tools import _job_facts
        job = _latest_job(obj)
        if job is None:
            return None
        return {'id': job.pk, **_job_facts(job, timezone.localtime())}

    def get_window_closes_at(self, obj):
        """When free replies stop being allowed: the same rule the sender uses."""
        from apps.communications.services.window import window_closes_at
        return window_closes_at(obj)

    def get_display_name(self, obj):
        return obj.display_name


class ConversationAssignSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()