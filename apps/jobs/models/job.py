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

    # ── After-hours (BM post-closing, awaiting cashier handover) ─────────
    INTAKE_HELD        = 'INTAKE_HELD'

    # ── Deprecated (kept for DB integrity, not used in new transitions) ──
    BRIEFED            = 'BRIEFED'
    DESIGN_IN_PROGRESS = 'DESIGN_IN_PROGRESS'
    QUEUED             = 'QUEUED'
    READY_FOR_PAYMENT  = 'READY_FOR_PAYMENT'

    # ── Lifecycle axes ────────────────────────────────────────
    # Three independent facts that the single `status` field cannot express
    # together: where the money is, where the physical work is, and whether
    # the customer has it. A job can be part-paid, still in production and
    # awaiting collection — one value cannot say that.
    #
    # `status` is retained and kept in sync while readers are migrated across.

    class Payment(models.TextChoices):
        UNPAID       = 'UNPAID',       'Unpaid'
        DEPOSIT_PAID = 'DEPOSIT_PAID', 'Deposit paid'
        SETTLED      = 'SETTLED',      'Settled'

    class Work(models.TextChoices):
        RECEIVED      = 'RECEIVED',      'Received'
        IN_PRODUCTION = 'IN_PRODUCTION', 'In production'
        FINISHING     = 'FINISHING',     'Finishing'
        QUALITY_CHECK = 'QUALITY_CHECK', 'Quality check'
        DONE          = 'DONE',          'Done'

    class Handover(models.TextChoices):
        AWAITING_COLLECTION = 'AWAITING_COLLECTION', 'Awaiting collection'
        OUT_FOR_DELIVERY    = 'OUT_FOR_DELIVERY',    'Out for delivery'
        HANDED_OVER         = 'HANDED_OVER',         'Handed over'

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
        (INTAKE_HELD,        'Intake Held'),
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
    PROFORMA = 'PROFORMA'
    CHANNEL_CHOICES = [
        (WALK_IN,  'Walk-in'),
        (WHATSAPP, 'WhatsApp'),
        (EMAIL,    'Email'),
        (PHONE,    'Phone'),
        (PROFORMA, 'Accepted proforma'),
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
    WALLET = 'WALLET'

    PAYMENT_METHOD_CHOICES = [
        (CASH,   'Cash'),
        (MOMO,   'Mobile Money'),
        (POS,    'POS'),
        (CREDIT, 'Credit Account'),
        (WALLET, 'Wallet Credit'),
    ]

    # ── Core fields ──────────────────────────────────────────────
    job_number = models.CharField(max_length=30, unique=True, blank=True)
    job_type   = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES)
    status     = models.CharField(max_length=30, choices=STATUS_CHOICES, default=DRAFT)

    # Owned by the cashier — the only point at which money enters.
    payment_state = models.CharField(
        max_length = 20,
        choices    = Payment.choices,
        default    = Payment.UNPAID,
        db_index   = True,
    )
    # Owned by the flow coordinator, who never meets a customer.
    # Instant jobs use only RECEIVED and DONE.
    work_state = models.CharField(
        max_length = 20,
        choices    = Work.choices,
        default    = Work.RECEIVED,
        db_index   = True,
    )
    # Owned by the attendant, the only customer-facing surface.
    # An attendant can never release a job that is not SETTLED, unless the
    # balance has been placed on a credit account by the cashier.
    handover_state = models.CharField(
        max_length = 20,
        choices    = Handover.choices,
        default    = Handover.AWAITING_COLLECTION,
        db_index   = True,
    )
    handed_over_at = models.DateTimeField(null=True, blank=True)
    handed_over_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.SET_NULL,
        null         = True,
        blank        = True,
        related_name = 'jobs_handed_over',
    )
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

    # ── Post-closing ──────────────────────────────────────────────
    post_closing = models.BooleanField(
        default   = False,
        help_text = 'True if job was created after branch closing time — BM only.',
    )
    post_closing_reason = models.TextField(
        blank     = True,
        help_text = 'Mandatory reason for post-closing job — entered by BM.',
    )
    post_closing_approved_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'post_closing_jobs',
        null         = True,
        blank        = True,
        help_text    = 'BM who approved this post-closing job.',
    )

    # ── Handover dispute (INTAKE_HELD jobs only) ────────────────────
    # Mirrors CashierFloat.physical_confirm_disputed — same pattern,
    # same escalation path to Regional Manager.
    handover_disputed = models.BooleanField(
        default   = False,
        help_text = 'True if the cashier reported not receiving cash from the BM for this job.',
    )
    handover_disputed_at = models.DateTimeField(null=True, blank=True)
    handover_disputed_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'handover_disputes_raised',
        null         = True,
        blank        = True,
        help_text    = 'Cashier who raised the dispute.',
    )
    handover_resolved_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the cashier affirms receipt (with or without a prior dispute).',
    )
    handover_resolved_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'handover_resolutions',
        null         = True,
        blank        = True,
        help_text    = 'Cashier who confirmed the handover.',
    )

    # ── Voided (DEPRECATED — never wired into JobStatusEngine, business
    # rules for this were never finalized; CANCELLED covers the standard
    # case. Do not build against this field without a fresh design
    # discussion — see void_reason/voided_by/voided_at below.) ────────

   # ── Credit ────────────────────────────────────────────────
    credit_account = models.ForeignKey(
        'finance.CreditAccount',
        on_delete    = models.PROTECT,
        related_name = 'jobs',
        null         = True,
        blank        = True,
        help_text    = 'Credit account used if payment method is CREDIT.',
    )
    partial_credit_amount = models.DecimalField(
        max_digits   = 10,
        decimal_places = 2,
        null         = True,
        blank        = True,
        help_text    = 'Amount added to credit account for partial credit payments.',
    )
    partial_credit_account = models.ForeignKey(
        'finance.CreditAccount',
        on_delete    = models.PROTECT,
        related_name = 'partial_credit_jobs',
        null         = True,
        blank        = True,
        help_text    = 'Credit account charged for the unpaid portion.',
    )

    # ── Notes ──
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['branch', 'daily_sheet'], name='job_branch_sheet_idx'),
            models.Index(fields=['branch', 'status'],      name='job_branch_status_idx'),
            models.Index(fields=['daily_sheet', 'status'], name='job_sheet_status_idx'),
            models.Index(fields=['branch', 'intake_by'],   name='job_branch_intake_idx'),
            models.Index(fields=['branch', 'created_at'],  name='job_branch_created_idx'),
            models.Index(fields=['daily_sheet', 'status', 'job_type'], name='job_sheet_status_type_idx'),
            models.Index(fields=['status'],                name='job_status_idx'),
        ]

    def __str__(self) -> str:
        return f"{self.job_number} — {self.title}"

    def save(self, *args, **kwargs) -> None:
        if not self.job_number:
            self.job_number = self._generate_job_number()
        super().save(*args, **kwargs)

    def _generate_job_number(self) -> str:
        from django.utils import timezone
        from django.db.models import Max
        year        = timezone.now().year
        branch_code = self.branch.code if self.branch else 'GEN'
        prefix      = f"FP-{branch_code}-{year}-"
        last = Job.objects.filter(
            branch=self.branch,
            job_number__startswith=prefix,
        ).aggregate(Max('job_number'))['job_number__max']
        if last:
            last_num = int(last.split('-')[-1])
        else:
            last_num = 0
        return f"{prefix}{str(last_num + 1).zfill(5)}"

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

    # ── Verification ─────────────────────────────────────────────

    # Channels where nobody is standing at the counter and nobody at the
    # branch has yet looked at what was sent. A walk-in needs no
    # verification — anything unclear is asked on the spot.
    #
    # PROFORMA is deliberately absent. A quote is built line by line by a
    # manager, agreed with the customer and converted deliberately; that is
    # more scrutiny than a verification, not less.
    REMOTE_CHANNELS = {'WHATSAPP', 'EMAIL', 'PHONE'}

    @property
    def needs_verification(self) -> bool:
        """
        Derived rather than stored, so there is no second source of truth
        to drift from the channel the job arrived on.
        """
        return self.intake_channel in self.REMOTE_CHANNELS

    @property
    def latest_verification(self):
        """Most recent check. Verifications are ordered newest first."""
        return self.verifications.first()

    @property
    def is_verified(self) -> bool:
        """Cleared for production. False where no check has passed yet."""
        latest = self.latest_verification
        return bool(latest and latest.passed)

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