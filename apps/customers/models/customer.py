from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.core.models import AuditModel


class CustomerProfile(AuditModel):
    """
    Registered customer profile.
    Phone number is the primary identifier across all channels.
    """

    # ── Customer Types ────────────────────────────────────────
    INDIVIDUAL  = 'INDIVIDUAL'
    BUSINESS    = 'BUSINESS'
    INSTITUTION = 'INSTITUTION'

    TYPE_CHOICES = [
        (INDIVIDUAL,  'Individual'),
        (BUSINESS,    'Business'),
        (INSTITUTION, 'Institution'),
    ]

    # ── Institution Subtypes ──────────────────────────────────
    SCHOOL = 'SCHOOL'
    CHURCH = 'CHURCH'
    NGO    = 'NGO'
    GOVT   = 'GOVT'
    OTHER  = 'OTHER'

    INSTITUTION_SUBTYPE_CHOICES = [
        (SCHOOL, 'School'),
        (CHURCH, 'Church / Religious'),
        (NGO,    'NGO / Non-profit'),
        (GOVT,   'Government / Public'),
        (OTHER,  'Other Institution'),
    ]

    # ── Loyalty Tiers ─────────────────────────────────────────
    REGULAR   = 'REGULAR'
    PREFERRED = 'PREFERRED'
    VIP       = 'VIP'

    TIER_CHOICES = [
        (REGULAR,   'Regular'),
        (PREFERRED, 'Preferred'),
        (VIP,       'VIP'),
    ]

    # ── Title choices ─────────────────────────────────────────
    MR          = 'MR'
    MRS         = 'MRS'
    MISS        = 'MISS'
    MS          = 'MS'
    MADAM       = 'MADAM'
    DR          = 'DR'
    PROF        = 'PROF'
    REV         = 'REV'
    ESQ         = 'ESQ'
    OTHER_TITLE = 'OTHER'

    TITLE_CHOICES = [
        (MR,          'Mr'),
        (MRS,         'Mrs'),
        (MISS,        'Miss'),
        (MS,          'Ms'),
        (MADAM,       'Madam'),
        (DR,          'Dr'),
        (PROF,        'Prof'),
        (REV,         'Rev'),
        (ESQ,         'Esq'),
        (OTHER_TITLE, 'Other'),
    ]

    # ── Gender choices ────────────────────────────────────────
    MALE       = 'MALE'
    FEMALE     = 'FEMALE'
    PREFER_NOT = 'PREFER_NOT'

    GENDER_CHOICES = [
        (MALE,       'Male'),
        (FEMALE,     'Female'),
        (PREFER_NOT, 'Prefer not to say'),
    ]

    # ── Preferred contact choices ─────────────────────────────
    CONTACT_WHATSAPP = 'WHATSAPP'
    CONTACT_CALL     = 'CALL'
    CONTACT_SMS      = 'SMS'
    CONTACT_EMAIL    = 'EMAIL'

    PREFERRED_CONTACT_CHOICES = [
        (CONTACT_WHATSAPP, 'WhatsApp'),
        (CONTACT_CALL,     'Call'),
        (CONTACT_SMS,      'SMS'),
        (CONTACT_EMAIL,    'Email'),
    ]

    # ── Core identity ─────────────────────────────────────────
    title = models.CharField(
        max_length=10,
        choices=TITLE_CHOICES,
        blank=True,
        help_text='Honorific title e.g. Mr, Dr, Prof',
    )
    title_other = models.CharField(
        max_length=50,
        blank=True,
        help_text='Custom title when title=OTHER',
    )
    first_name  = models.CharField(max_length=100, blank=True)
    last_name   = models.CharField(max_length=100, blank=True)
    gender      = models.CharField(
        max_length=10,
        choices=GENDER_CHOICES,
        blank=True,
    )
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        help_text='Optional — used for birthday messages',
    )
    phone = models.CharField(max_length=20, unique=True)
    secondary_phone = models.CharField(
        max_length=20,
        blank=True,
        help_text='Alternative number — searchable but not used for payments or automated messages',
    )
    email = models.EmailField(blank=True)
    preferred_contact = models.CharField(
        max_length=10,
        choices=PREFERRED_CONTACT_CHOICES,
        blank=True,
        help_text='How this customer prefers to be contacted',
    )

    # ── Affiliation ───────────────────────────────────────────
    affiliation = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='affiliated_individuals',
        help_text='Institution or business this individual is affiliated with',
    )
    affiliation_active = models.BooleanField(
        default=True,
        help_text='Set to False if individual has left the affiliated organisation',
    )

    # ── Organisation details ──────────────────────────────────
    company_name = models.CharField(
        max_length=150,
        blank=True,
        help_text='Company, school, or church name if applicable',
    )
    address = models.TextField(
        blank=True,
        help_text='Physical address of customer or organisation',
    )

    # ── Type classification ───────────────────────────────────
    customer_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=INDIVIDUAL,
    )
    institution_subtype = models.CharField(
        max_length=20,
        choices=INSTITUTION_SUBTYPE_CHOICES,
        blank=True,
        help_text='Only applicable when customer_type is INSTITUTION',
    )
    
    # ── Engagement ────────────────────────────────────────────
    visit_count = models.PositiveIntegerField(default=0)
    total_spend = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text='Lifetime spend across all completed jobs. Auto-updated on job completion.',
    )
    tier        = models.CharField(
        max_length=20,
        choices=TIER_CHOICES,
        default=REGULAR,
    )
    confidence_score = models.PositiveIntegerField(
        default=0,
        help_text=(
            'System-computed score 0–100 based on job volume, '
            'payment consistency, profile completeness, and tenure. '
            'Score ≥ 50 triggers a credit eligibility recommendation.'
        ),
    )

    # ── Branch ────────────────────────────────────────────────
    preferred_branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='preferred_customers',
    )
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customers',
        help_text='Branch where this customer was first recorded',
    )

    # ── Flags ─────────────────────────────────────────────────
    is_priority = models.BooleanField(default=False)
    is_walkin   = models.BooleanField(
        default=False,
        help_text='True if auto-created from a walk-in receipt delivery',
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-visit_count', 'first_name']

    def __str__(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return f"{name} ({self.phone})" if name else self.phone

    @property
    def title_display(self) -> str:
        """Returns the display label for the title."""
        if not self.title:
            return ''
        if self.title == self.OTHER_TITLE:
            return self.title_other or ''
        return dict(self.TITLE_CHOICES).get(self.title, '')

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def titled_name(self) -> str:
        """Title + last name for formal addressing e.g. receipts, messages."""
        parts = [self.title_display, self.last_name]
        return ' '.join(p for p in parts if p).strip() or self.full_name

    @property
    def display_name(self) -> str:
        """Company name if set, otherwise full name."""
        return self.company_name or self.full_name or self.phone

# ── Customer Edit Audit Log ───────────────────────────────────────────────────

class CustomerEditLog(models.Model):
    """
    Immutable audit record of every field change made to a CustomerProfile.
    Never updated — only created.
    """
    customer   = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name='edit_logs',
    )
    changed_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        related_name='customer_edits',
    )
    field_name  = models.CharField(max_length=100)
    old_value   = models.TextField(blank=True)
    new_value   = models.TextField(blank=True)
    changed_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError('CustomerEditLog records are immutable.')
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.changed_by} changed {self.field_name} "
            f"on {self.customer} at {self.changed_at}"
        )


# ── Signal: recompute confidence score after each job completion ──────────────
@receiver(post_save, sender='jobs.Job')
def update_customer_confidence(sender, instance, **kwargs):
    """
    Updates visit_count, total_spend and confidence score when a job completes.
    Only fires when the job is COMPLETE and linked to a customer.
    If the score crosses the recommendation threshold, notifies the BM.
    """
    if instance.status != 'COMPLETE':
        return
    if not instance.customer_id:
        return

    try:
        from apps.customers.credit_engine import CreditEngine
        from apps.notifications.services import notify
        from django.db.models import F
        from decimal import Decimal

        customer = instance.customer

        # Increment visit count and total spend atomically
        amount = Decimal(str(instance.amount_paid or 0))
        CustomerProfile.objects.filter(pk=customer.pk).update(
            visit_count = F('visit_count') + 1,
            total_spend = F('total_spend') + amount,
        )
        customer.refresh_from_db()

        new_score = CreditEngine.compute_confidence_score(customer)

        # Notify BM if customer just crossed the recommendation threshold
        # and doesn't already have a credit account
        if CreditEngine.should_recommend(customer):
            branch = instance.branch
            if branch:
                from apps.accounts.models import CustomUser
                bm = CustomUser.objects.filter(
                    branch=branch,
                    role__name='BRANCH_MANAGER',
                ).first()
                if bm:
                    notify(
                        recipient=bm,
                        message=(
                            f"{customer.display_name} may be eligible for a credit account "
                            f"(confidence score: {new_score}). Consider nominating them."
                        ),
                        category='CREDIT',
                        link=f'/customers/{customer.id}/',
                    )
    except Exception:
        pass  # never let a signal crash a job save