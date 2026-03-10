from django.db import models
from django.conf import settings


class Notification(models.Model):

    class Verb(models.TextChoices):
        # Jobs
        JOB_CREATED       = 'job_created',       'Job Created'
        JOB_STATUS_CHANGE = 'job_status_changed', 'Job Status Changed'
        JOB_ROUTED        = 'job_routed',         'Job Routed'
        # Communications
        MESSAGE_RECEIVED  = 'message_received',   'Message Received'
        CONVERSATION_ASSIGNED = 'conversation_assigned', 'Conversation Assigned'
        # HR
        EMPLOYEE_CREATED  = 'employee_created',   'Employee Created'
        # System
        SYSTEM            = 'system',             'System'

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        db_index=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='triggered_notifications',
    )
    verb    = models.CharField(max_length=64, choices=Verb.choices, db_index=True)
    message = models.TextField()
    link    = models.CharField(max_length=500, blank=True, default='')
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['recipient', 'created_at']),
        ]

    def __str__(self):
        return f'[{self.verb}] → {self.recipient} | read={self.is_read}'

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=['is_read'])