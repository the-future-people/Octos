from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):

    actor_name = serializers.SerializerMethodField()
    time_ago   = serializers.SerializerMethodField()

    class Meta:
        model  = Notification
        fields = [
            'id', 'verb', 'message', 'link',
            'is_read', 'created_at',
            'actor_name', 'time_ago',
        ]
        read_only_fields = fields

    def get_actor_name(self, obj):
        if obj.actor:
            return obj.actor.full_name or obj.actor.email
        return None

    def get_time_ago(self, obj):
        from django.utils import timezone
        from datetime import timedelta

        now  = timezone.now()
        diff = now - obj.created_at

        if diff < timedelta(minutes=1):
            return 'just now'
        if diff < timedelta(hours=1):
            m = int(diff.total_seconds() / 60)
            return f'{m}m ago'
        if diff < timedelta(days=1):
            h = int(diff.total_seconds() / 3600)
            return f'{h}h ago'
        if diff < timedelta(days=7):
            d = diff.days
            return f'{d}d ago'
        return obj.created_at.strftime('%-d %b %Y')