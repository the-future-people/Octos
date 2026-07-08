from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


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
        # Reminders (harmonized system — see apps/notifications/management/commands/generate_reminders.py)
        SHIFT_ENDING       = 'shift_ending',       'Shift Ending Soon'
        TASK_CHECKPOINT    = 'task_checkpoint',    'Personal Task Reminder'
        # System
        SYSTEM            = 'system',             'System'

    class Category(models.TextChoices):
        ALERT    = 'ALERT',    'Alert'
        REMINDER = 'REMINDER', 'Reminder'

    class DisplayMode(models.TextChoices):
        PASSIVE      = 'PASSIVE',      'Passive (bell only)'
        INTERRUPTIVE = 'INTERRUPTIVE', 'Interruptive (modal + bell)'

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

    # ── Harmonized reminder/notification fields ──────────────────────
    category = models.CharField(
        max_length=10, choices=Category.choices, default=Category.ALERT, db_index=True,
        help_text='ALERT = event-driven (existing behavior). REMINDER = time/schedule-driven.',
    )
    display_mode = models.CharField(
        max_length=15, choices=DisplayMode.choices, default=DisplayMode.PASSIVE, db_index=True,
        help_text='PASSIVE = bell only. INTERRUPTIVE = full-screen modal until dismissed, plus bell.',
    )
    requires_pin = models.BooleanField(
        default=False,
        help_text='True for personal-note reminders — message stays generic, real content is '
                   'never exposed here, only accessible via the PIN-gated personal_notes endpoint.',
    )
    dedupe_key = models.CharField(
        max_length=200, blank=True, default='', db_index=True,
        help_text='Used with get_or_create to prevent duplicate reminder creation across task runs, '
                   'e.g. "shift_ending-{user_id}-{date}-{bucket}". Blank for one-off ALERT notifications.',
    )

    # Generic link back to the real source (TaskCheckpoint, etc.) — kept
    # nullable and content-free so Notification never needs to know
    # about or duplicate private/domain-specific data.
    content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True,
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    source = GenericForeignKey('content_type', 'object_id')

    class Meta:
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['recipient', 'created_at']),
            models.Index(fields=['recipient', 'display_mode', 'is_read']),
            models.Index(fields=['dedupe_key']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['dedupe_key'],
                condition=~models.Q(dedupe_key=''),
                name='unique_nonblank_dedupe_key',
            ),
        ]

    def __str__(self):
        return f'[{self.verb}] → {self.recipient} | read={self.is_read}'

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=['is_read'])