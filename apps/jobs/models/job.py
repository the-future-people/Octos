from django.db import models
from apps.core.models import AuditModel


class Job(AuditModel):
    """
    The central model for all work done at Farhat Printing Press.
    Every job — instant, production or design — lives here.
    """

    # Job Types
    INSTANT = 'INSTANT'
    PRODUCTION = 'PRODUCTION'
    DESIGN = 'DESIGN'

    JOB_TYPE_CHOICES = [
        (INSTANT, 'Instant'),
        (PRODUCTION, 'Production'),
        (DESIGN, 'Design'),
    ]

    # Job Statuses
    DRAFT = 'DRAFT'
    CONFIRMED = 'CONFIRMED'
    BRIEFED = 'BRIEFED'
    DESIGN_IN_PROGRESS = 'DESIGN_IN_PROGRESS'
    SAMPLE_SENT = 'SAMPLE_SENT'
    REVISION_REQUESTED = 'REVISION_REQUESTED'
    DESIGN_APPROVED = 'DESIGN_APPROVED'
    QUEUED = 'QUEUED'
    IN_PROGRESS = 'IN_PROGRESS'
    READY_FOR_PAYMENT = 'READY_FOR_PAYMENT'
    PAID = 'PAID'
    OUT_FOR_DELIVERY = 'OUT_FOR_DELIVERY'
    COMPLETE = 'COMPLETE'
    CANCELLED = 'CANCELLED'

    STATUS_CHOICES = [
        (DRAFT, 'Draft'),
        (CONFIRMED, 'Confirmed'),
        (BRIEFED, 'Briefed'),
        (DESIGN_IN_PROGRESS, 'Design In Progress'),
        (SAMPLE_SENT, 'Sample Sent'),
        (REVISION_REQUESTED, 'Revision Requested'),
        (DESIGN_APPROVED, 'Design Approved'),
        (QUEUED, 'Queued'),
        (IN_PROGRESS, 'In Progress'),
        (READY_FOR_PAYMENT, 'Ready for Payment'),
        (PAID, 'Paid'),
        (OUT_FOR_DELIVERY, 'Out for Delivery'),
        (COMPLETE, 'Complete'),
        (CANCELLED, 'Cancelled'),
    ]

    # Intake Channels
    WALK_IN = 'WALK_IN'
    WHATSAPP = 'WHATSAPP'
    EMAIL = 'EMAIL'
    PHONE = 'PHONE'

    CHANNEL_CHOICES = [
        (WALK_IN, 'Walk-in'),
        (WHATSAPP, 'WhatsApp'),
        (EMAIL, 'Email'),
        (PHONE, 'Phone'),
    ]

    # Priority
    NORMAL = 'NORMAL'
    HIGH = 'HIGH'
    URGENT = 'URGENT'

    PRIORITY_CHOICES = [
        (NORMAL, 'Normal'),
        (HIGH, 'High'),
        (URGENT, 'Urgent'),
    ]

    # Core fields
    job_number = models.CharField(max_length=30, unique=True, blank=True)
    job_type = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=DRAFT)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=NORMAL)

    # Branches
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='jobs',
        help_text='Originating branch — owns the customer relationship'
    )
    assigned_to = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='assigned_jobs',
        null=True,
        blank=True,
        help_text='Executing branch if routed'
    )

    # Customer
    customer = models.ForeignKey(
        'customers.CustomerProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='jobs'
    )

    # Job details
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    specifications = models.JSONField(default=dict, blank=True)

    # Intake
    intake_channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default=WALK_IN)
    intake_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='jobs_created',
        null=True,
        blank=True
    )

    # Timing & cost
    estimated_time = models.PositiveIntegerField(null=True, blank=True, help_text='Minutes')
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    final_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    deadline = models.DateTimeField(null=True, blank=True)

    # Routing
    is_routed = models.BooleanField(default=False)
    routing_reason = models.TextField(blank=True)

    # Notes
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.job_number} — {self.title}"

    def save(self, *args, **kwargs):
        if not self.job_number:
            self.job_number = self._generate_job_number()
        super().save(*args, **kwargs)

    def _generate_job_number(self):
        from django.utils import timezone
        year = timezone.now().year
        branch_code = self.branch.code if self.branch else 'GEN'
        last = Job.objects.filter(
            branch=self.branch,
            created_at__year=year
        ).count() + 1
        return f"FP-{branch_code}-{year}-{str(last).zfill(5)}"

    @property
    def is_instant(self):
        return self.job_type == self.INSTANT

    @property
    def is_production(self):
        return self.job_type == self.PRODUCTION

    @property
    def is_design(self):
        return self.job_type == self.DESIGN