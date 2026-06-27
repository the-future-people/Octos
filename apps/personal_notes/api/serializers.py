from rest_framework import serializers
from apps.personal_notes.models import PersonalNote


class PersonalNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PersonalNote
        fields = [
            'id', 'title', 'body', 'color',
            'reminder_at', 'reminder_dismissed',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class SetPinSerializer(serializers.Serializer):
    pin = serializers.RegexField(r'^\d{4}$', error_messages={
        'invalid': 'PIN must be exactly 4 digits.'
    })


class VerifyPinSerializer(serializers.Serializer):
    pin = serializers.RegexField(r'^\d{4}$', error_messages={
        'invalid': 'PIN must be exactly 4 digits.'
    })