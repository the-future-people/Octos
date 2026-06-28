from rest_framework import serializers
from apps.personal_notes.models import PersonalNote, TaskCheckpoint


class TaskCheckpointSerializer(serializers.ModelSerializer):
    class Meta:
        model  = TaskCheckpoint
        fields = [
            'id', 'scheduled_at', 'acknowledged',
            'acknowledged_at', 'is_final',
        ]
        read_only_fields = fields


class PersonalNoteSerializer(serializers.ModelSerializer):
    checkpoints = TaskCheckpointSerializer(many=True, read_only=True)

    class Meta:
        model  = PersonalNote
        fields = [
            'id', 'title', 'body', 'color',
            'note_type', 'status', 'due_date', 'completed_at',
            'reminder_at', 'reminder_dismissed',
            'checkpoints',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'completed_at', 'created_at', 'updated_at']


class SetPinSerializer(serializers.Serializer):
    pin = serializers.RegexField(r'^\d{4}$', error_messages={
        'invalid': 'PIN must be exactly 4 digits.'
    })


class VerifyPinSerializer(serializers.Serializer):
    pin = serializers.RegexField(r'^\d{4}$', error_messages={
        'invalid': 'PIN must be exactly 4 digits.'
    })