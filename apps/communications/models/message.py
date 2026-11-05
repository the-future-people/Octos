from django.db import models
from apps.core.models import AuditModel


class Message(AuditModel):
    """
    A single message within a conversation.
    Can be inbound (from customer) or outbound (from staff or Octos).
    Every staff reply is logged against the staff member who sent it.
    """

    # Direction
    INBOUND = 'INBOUND'
    OUTBOUND = 'OUTBOUND'

    DIRECTION_CHOICES = [
        (INBOUND, 'Inbound'),
        (OUTBOUND, 'Outbound'),
    ]

    # Channel
    WHATSAPP = 'WHATSAPP'
    EMAIL = 'EMAIL'
    PHONE = 'PHONE'
    WALK_IN = 'WALK_IN'
    SYSTEM = 'SYSTEM'

    CHANNEL_CHOICES = [
        (WHATSAPP, 'WhatsApp'),
        (EMAIL, 'Email'),
        (PHONE, 'Phone'),
        (WALK_IN, 'Walk-in'),
        (SYSTEM, 'System'),
    ]

    # Message Type
    TEXT = 'TEXT'
    IMAGE = 'IMAGE'
    VIDEO = 'VIDEO'
    DOCUMENT = 'DOCUMENT'
    AUDIO = 'AUDIO'
    NOTE = 'NOTE'

    TYPE_CHOICES = [
        (TEXT, 'Text'),
        (IMAGE, 'Image'),
        (VIDEO, 'Video'),
        (DOCUMENT, 'Document'),
        (AUDIO, 'Audio'),
        (NOTE, 'Internal Note'),
    ]

    # Status. Outbound messages move forward only:
    # QUEUED → SENT → DELIVERED → READ. FAILED can arrive at any point.
    QUEUED = 'QUEUED'
    SENT = 'SENT'
    DELIVERED = 'DELIVERED'
    READ = 'READ'
    FAILED = 'FAILED'

    STATUS_CHOICES = [
        (QUEUED, 'Queued'),
        (SENT, 'Sent'),
        (DELIVERED, 'Delivered'),
        (READ, 'Read'),
        (FAILED, 'Failed'),
    ]

    conversation = models.ForeignKey(
        'communications.Conversation',
        on_delete=models.CASCADE,
        related_name='messages'
    )
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    message_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TEXT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=SENT)
    error = models.CharField(
        max_length=500,
        blank=True,
        help_text="Why sending failed, in the provider's words. Empty when it didn't.",
    )
    kind = models.CharField(
        max_length=30,
        blank=True,
        db_index=True,
        help_text='What a system message is about (welcome, paid, ready, late…), '
                  'the same words as the SMS log. Blank for conversation replies.',
    )

    # Content
    body = models.TextField(blank=True)
    media_url = models.URLField(blank=True)
    media_file = models.FileField(
        upload_to='communications/media/%Y/%m/',
        null=True,
        blank=True
    )
        # What the file is, kept when it arrives, so the inbox and Octos can
    # name it ("albion-sticker.pdf, 1 page") and price by its page count.
    media_name  = models.CharField(max_length=255, blank=True)
    media_mime  = models.CharField(max_length=100, blank=True)
    media_size  = models.PositiveIntegerField(null=True, blank=True)
    media_pages = models.PositiveSmallIntegerField(null=True, blank=True)
    media_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="The provider's id for an attached file, used to download it. "
                  "WhatsApp keeps media for about 30 days.",
    )

    # Sender
    sent_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_messages',
        help_text='Staff member who sent this. Empty for inbound messages, '
                  'and for outbound messages Octos sent itself.'
    )

    # External IDs for third party webhooks
    external_id = models.CharField(
        max_length=255,
        blank=True,
        help_text='WhatsApp message ID, Twilio SID etc.'
    )

    # Call specific fields
    call_duration = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Call duration in seconds'
    )
    caller_id = models.CharField(max_length=20, blank=True)

    # Internal note flag
    is_internal_note = models.BooleanField(
        default=False,
        help_text='Internal notes are visible to staff only, never sent to customer'
    )

    # Read tracking
    read_by = models.ManyToManyField(
        'accounts.CustomUser',
        blank=True,
        related_name='read_messages'
    )

    class Meta:
        ordering = ['created_at']
        constraints = [
            # Meta retries deliveries. The constraint is the duplicate
            # check: the second insert fails, and that failure is how the
            # webhook knows it has seen this message before. Blank ids
            # (staff replies, calls, notes) are exempt.
            models.UniqueConstraint(
                fields=['channel', 'external_id'],
                condition=~models.Q(external_id=''),
                name='uniq_message_external_id_per_channel',
            ),
        ]

    def __str__(self):
        direction = '←' if self.direction == self.INBOUND else '→'
        return f"{direction} {self.channel} | {self.body[:50]}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update conversation last message info
        if not self.is_internal_note:
            conv = self.conversation
            conv.last_message_at = self.created_at
            conv.last_message_preview = self.body[:200] if self.body else f'[{self.message_type}]'
            if self.direction == self.INBOUND:
                conv.unread_count = models.F('unread_count') + 1
            conv.save(update_fields=['last_message_at', 'last_message_preview', 'unread_count'])