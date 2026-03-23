from django.db import models
from apps.core.models import AuditModel


class Job(AuditModel):
    """
    The central model for all work done at Farhat Printing Press.
    Every job — instant, production or design — lives here.
    """

    # ── Job Types ────────────────────────────────────────────────
    INSTANT    = 'INSTANT'
    PRODUCTION = 'PRODUCTION'
    DESIGN     = 'DESIGN'

    JOB_TYPE_CHOICES = [
        (INSTANT,    'Instant'),
        (PRODUCTION, 'Production'),
        (DESIGN,     'Design'),
    ]

    # ── Job Statuses ─────────────────────────────────────────────
    # Shared
    DRAFT             = 'DRAFT'
    PENDING_PAYMENT   = 'PENDING_PAYMENT'
    PAID              = 'PAID'
    IN_PROGRESS       = 'IN_PROGRESS'
    COMPLETE          = 'COMPLETE'
    CANCELLED         = 'CANCELLED'
    VOIDED            = 'VOIDED'

    # Production + Design
    CONFIRMED         = 'CONFIRMED'
    READY             = 'READY'
    OUT_FOR_DELIVERY  = 'OUT_FOR_DELIVERY'
    HALTED            = 'HALTED'

    # Design only
    SAMPLE_SENT        = 'SAMPLE_SENT'
    REVISION_REQUESTED = 'REVISION_REQUESTED'
    DESIGN_APPROVED    = 'DESIGN_APPROVED'

    # ── Deprecated (kept for DB integrity, not used in new transitions) ──
    BRIEFED            = 'BRIEFED'
    DESIGN_IN_PROGRESS = 'DESIGN_IN_PROGRESS'
    QUEUED             = 'QUEUED'
    READY_FOR_PAYMENT  = 'READY_FOR_PAYMENT'

    STATUS_CHOICES = [
        # Active statuses
        (DRAFT,              'Draft'),
        (PENDING_PAYMENT,    'Pending Payment'),
        (PAID,               'Paid'),
        (CONFIRMED,          'Confirmed'),
        (IN_PROGRESS,        'In Progress'),
        (READY,              'Ready'),
        (OUT_FOR_DELIVERY,   'Out for Delivery'),
        (COMPLETE,           'Complete'),
        (CANCELLED,          'Cancelled'),
        (VOIDED,             'Voided'),
        (HALTED,             'Halted'),
        (SAMPLE_SENT,        'Sample Sent'),
        (REVISION_REQUESTED, 'Revision Requested'),
        (DESIGN_APPROVED,    'Design Approved'),
        # Deprecated — retained for existing data only
        ('BRIEFED',            'Briefed (Deprecated)'),
        ('DESIGN_IN_PROGRESS', 'Design In Progress (Deprecated)'),
        ('QUEUED',             'Queued (Deprecated)'),
        ('READY_FOR_PAYMENT',  'Ready for Payment (Deprecated)'),
    ]

    # ── Deposit Choices ──────────────────────────────────────────
    DEPOSIT_70  = 70
    DEPOSIT_100 = 100

    DEPOSIT_CHOICES = [
        (DEPOSIT_70,  '70% Deposit'),
        (DEPOSIT_100, '100% (Full Payment)'),
    ]

    # ── Intake Channels ──────────────────────────────────────────
    WALK_IN  = 'WALK_IN'
    WHATSAPP = 'WHATSAPP'
    EMAIL    = 'EMAIL'
    PHONE    = 'PHONE'

    CHANNEL_CHOICES = [
        (WALK_IN,  'Walk-in'),
        (WHATSAPP, 'WhatsApp'),
        (EMAIL,    'Email'),
        (PHONE,    'Phone'),
    ]

    # ── Priority ─────────────────────────────────────────────────
    NORMAL = 'NORMAL'
    HIGH   = 'HIGH'
    URGENT = 'URGENT'

    PRIORITY_CHOICES = [
        (NORMAL, 'Normal'),
        (HIGH,   'High'),
        (URGENT, 'Urgent'),
    ]

    # ── Payment Methods ──────────────────────────────────────────
    CASH   = 'CASH'
    MOMO   = 'MOMO'
    POS    = 'POS'
    CREDIT = 'CREDIT'

    PAYMENT_METHOD_CHOICES = [
        (CASH,   'Cash'),
        (MOMO,   'Mobile Money'),
        (POS,    'POS'),
        (CREDIT, 'Credit Account'),
    ]

    # ── Core fields ──────────────────────────────────────────────
    job_number = models.CharField(max_length=30, unique=True, blank=True)
    job_type   = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES)
    status     = models.CharField(max_length=30, choices=STATUS_CHOICES, default=DRAFT)
    priority   = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=NORMAL)

    # ── Branches ─────────────────────────────────────────────────
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='jobs',
        help_text='Originating branch — owns the customer relationship',
    )
    assigned_to = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='assigned_jobs',
        null=True,
        blank=True,
        help_text='Executing branch if routed',
    )

    # ── Customer ─────────────────────────────────────────────────
    customer = models.ForeignKey(
        'customers.CustomerProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='jobs',
    )

    # ── Job details ──────────────────────────────────────────────
    title          = models.CharField(max_length=255)
    description    = models.TextField(blank=True)
    specifications = models.JSONField(default=dict, blank=True)

    # ── Intake ───────────────────────────────────────────────────
    intake_channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        default=WALK_IN,
    )
    intake_by      = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='jobs_created',
        null=True,
        blank=True,
    )

    # ── Payment ──────────────────────────────────────────────────
    payment_method = models.CharField(
        max_length=10,
        choices=PAYMENT_METHOD_CHOICES,
        blank=True,
        default='',
        help_text='Set by cashier at payment confirmation',
    )
    deposit_percentage = models.PositiveSmallIntegerField(
        choices=DEPOSIT_CHOICES,
        default=DEPOSIT_100,
        help_text='Percentage of estimated cost collected at payment',
    )
    amount_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Actual amount paid by customer — set by cashier on confirmation',
    )
    momo_reference = models.CharField(
        max_length=50,
        blank=True,
        help_text='MoMo transaction reference — mandatory for MoMo payments',
    )
    pos_approval_code = models.CharField(
        max_length=50,
        blank=True,
        help_text='POS terminal approval code — mandatory for POS payments',
    )

    # ── Daily sheet linkage ───────────────────────────────────────
    daily_sheet = models.ForeignKey(
        'finance.DailySalesSheet',
        on_delete=models.PROTECT,
        related_name='jobs',
        null=True,
        blank=True,
        help_text='The daily sheet this job belongs to — set on creation',
    )

    # ── Proforma linkage ──────────────────────────────────────────
    proforma = models.ForeignKey(
        'jobs.ProformaInvoice',
        on_delete=models.SET_NULL,
        related_name='converted_jobs',
        null=True,
        blank=True,
        help_text='Proforma invoice this job was created from, if any',
    )

    # ── Void ──────────────────────────────────────────────────────
    void_reason = models.TextField(
        blank=True,
        help_text='Mandatory explanation if job is voided — BM authorised only',
    )
    voided_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='jobs_voided',
        null=True,
        blank=True,
    )
    voided_at = models.DateTimeField(null=True, blank=True)

    # ── Cancellation damages ──────────────────────────────────────
    cancellation_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='10% of full job value — applied when cancelled after IN_PROGRESS',
    )

    # ── Timing & cost ────────────────────────────────────────────
    estimated_time = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Minutes',
    )
    estimated_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    final_cost     = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    deadline       = models.DateTimeField(null=True, blank=True)

    # ── Routing ──────────────────────────────────────────────────
    is_routed      = models.BooleanField(default=False)
    routing_reason = models.TextField(blank=True)

    # ── Carry forward ─────────────────────────────────────────────
    carried_forward = models.BooleanField(
        default=False,
        help_text='True if this job was unpaid at sheet close and carried to next day.',
    )

    # ── Notes ────────────────────────────────────────────────────
    # ── Draft ────────────────────────────────────────────────────────────────
    draft_expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Auto-set to created_at + 3 days for DRAFT jobs. Null for all other statuses.',
    )
    abandoned_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when a draft expires or is manually discarded.',
    )
    # ── Cash handling ─────────────────────────────────────────────────────────
    cash_tendered = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text='Amount of cash given by customer',
    )
    change_given = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text='Change returned to customer',
    )

    # ── Notes ──
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"{self.job_number} — {self.title}"

    def save(self, *args, **kwargs) -> None:
        if not self.job_number:
            self.job_number = self._generate_job_number()
        super().save(*args, **kwargs)

    def _generate_job_number(self) -> str:
        from django.utils import timezone
        year        = timezone.now().year
        branch_code = self.branch.code if self.branch else 'GEN'
        last        = Job.objects.filter(
            branch=self.branch,
            created_at__year=year,
        ).count() + 1
        return f"FP-{branch_code}-{year}-{str(last).zfill(5)}"

    # ── Convenience properties ────────────────────────────────────
    @property
    def is_instant(self) -> bool:
        return self.job_type == self.INSTANT

    @property
    def is_production(self) -> bool:
        return self.job_type == self.PRODUCTION

    @property
    def is_design(self) -> bool:
        return self.job_type == self.DESIGN

    @property
    def balance_due(self):
        """Remaining amount owed after deposit."""
        if self.estimated_cost is None:
            return None
        paid = self.amount_paid or 0
        return max(self.estimated_cost - paid, 0)

    @property
    def is_fully_paid(self) -> bool:
        if self.estimated_cost is None:
            return False
        return (self.amount_paid or 0) >= self.estimated_cost

    @property
    def cancellation_fee_due(self):
        """10% of full job value — only applies when cancelled after IN_PROGRESS."""
        if self.estimated_cost is None:
            return None
        return round(self.estimated_cost * 10 / 100, 2)
    
    @property
    def computed_total(self):
        """Sum of all line item totals."""
        from django.db.models import Sum
        return self.line_items.aggregate(
            total=Sum('line_total')
        )['total'] or 0

    @property
    def line_item_summary(self) -> str:
        """Short summary of services — e.g. 'Photocopy, Binding, Envelope'"""
        names = list(
            self.line_items.values_list('service__name', flat=True)
        )
        if not names:
            return self.title or '—'
        overflow = len(names) - 3
        base = ', '.join(names[:3])
        return f"{base} +{overflow} more" if overflow > 0 else base