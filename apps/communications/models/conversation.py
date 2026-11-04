from django.db import models
from apps.core.models import AuditModel


class Conversation(AuditModel):
    """
    A threaded conversation with a customer across any channel.

    Branch conversations: one per customer per branch per channel.

    Company conversations (branch is null): one per phone per channel.
    WhatsApp arrives on one central number, the customer never says which
    branch they mean, and any branch can answer, so there is no branch to
    record. A branch can be linked later through a job.

    The two need separate uniqueness rules because Postgres treats nulls
    as distinct: unique_together alone would let a second company thread
    open for the same number.
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
        null=True,
        blank=True,
        related_name='conversations',
        help_text='Empty for company conversations, such as the central WhatsApp number.',
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
        constraints = [
            models.UniqueConstraint(
                fields=['contact_phone', 'channel'],
                condition=models.Q(branch__isnull=True),
                name='uniq_company_conversation_per_phone',
            ),
        ]

    def __str__(self):
        contact = self.contact_name or self.contact_phone or self.contact_email
        where = self.branch.name if self.branch_id else 'all branches'
        return f"{contact} @ {where} ({self.channel})"

    @property
    def display_name(self):
        if self.customer:
            return self.customer.full_name
        return self.contact_name or self.contact_phone or self.contact_email