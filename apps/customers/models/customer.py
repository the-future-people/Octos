from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.core.models import AuditModel


class CustomerProfile(AuditModel):
    """
    Registered customer profile.
    Phone number is the primary identifier across all channels.
    """

    # ── Loyalty Tiers ─────────────────────────────────────────
    REGULAR   = 'REGULAR'
    PREFERRED = 'PREFERRED'
    VIP       = 'VIP'

    TIER_CHOICES = [
        (REGULAR,   'Regular'),
        (PREFERRED, 'Preferred'),
        (VIP,       'VIP'),
    ]

    # ── Core identity ─────────────────────────────────────────
    first_name  = models.CharField(max_length=100, blank=True)
    last_name   = models.CharField(max_length=100, blank=True)
    phone       = models.CharField(max_length=20, unique=True)
    email       = models.EmailField(blank=True)

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

    # ── Engagement ────────────────────────────────────────────
    visit_count = models.PositiveIntegerField(default=1)
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
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def display_name(self) -> str:
        """Company name if set, otherwise full name."""
        return self.company_name or self.full_name or self.phone


# ── Signal: recompute confidence score after each job completion ──────────────
@receiver(post_save, sender='jobs.Job')
def update_customer_confidence(sender, instance, **kwargs):
    """
    Recomputes the customer's confidence score whenever a job is saved.
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

        customer = instance.customer
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