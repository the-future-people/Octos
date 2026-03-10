from django.db import models
from apps.core.models import AuditModel


class Conversation(AuditModel):
    """
    A threaded conversation with a customer across any channel.
    One conversation per customer per branch.
    All channels from the same customer collapse into one thread.
    """

    # Status
    OPEN = 'OPEN'
    PENDING = 'PENDING'
    RESOLVED = 'RESOLVED'
    SPAM = 'SPAM'

    STATUS_CHOICES = [
        (OPEN, 'Open'),
        (PENDING, 'Pending'),
        (RESOLVED, 'Resolved'),
        (SPAM, 'Spam'),
    ]

    # Channel
    WHATSAPP = 'WHATSAPP'
    EMAIL = 'EMAIL'
    PHONE = 'PHONE'
    WALK_IN = 'WALK_IN'

    CHANNEL_CHOICES = [
        (WHATSAPP, 'WhatsApp'),
        (EMAIL, 'Email'),
        (PHONE, 'Phone'),
        (WALK_IN, 'Walk-in'),
    ]

    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='conversations'
    )
    customer = models.ForeignKey(
        'customers.CustomerProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conversations'
    )

    # Contact identity before profile is created
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_name = models.CharField(max_length=150, blank=True)

    # Primary channel this conversation started on
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)

    # Assignment
    assigned_to = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_conversations'
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN)
    unread_count = models.PositiveIntegerField(default=0)
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_message_preview = models.CharField(max_length=200, blank=True)

    # Linked jobs
    jobs = models.ManyToManyField(
        'jobs.Job',
        blank=True,
        related_name='conversations'
    )

    class Meta:
        ordering = ['-last_message_at']
        unique_together = [['branch', 'contact_phone', 'channel']]

    def __str__(self):
        contact = self.contact_name or self.contact_phone or self.contact_email
        return f"{contact} @ {self.branch.name} ({self.channel})"

    @property
    def display_name(self):
        if self.customer:
            return self.customer.full_name
        return self.contact_name or self.contact_phone or self.contact_email