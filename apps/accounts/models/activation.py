from django.db import models
from apps.core.models import AuditModel


class PendingActivation(AuditModel):
    """
    Tracks a scheduled employee activation — either a new hire
    completing onboarding, or an existing staff member whose role
    is changing on a future date.

    Lifecycle:
      PENDING   — created by HR during onboarding verification.
                  CustomUser account exists with employment_status=SHADOW.
      SHADOW    — start_date is in the future; user has read-only access.
      ACTIVATED — Celery task has fired, user is now ACTIVE with full access.
      CANCELLED — HR cancelled before activation date.

    For new hires:
      applicant is set, credentials are generated, shadow_days applies.

    For existing staff role changes (e.g. Khofi BM → Regional Manager):
      applicant is null, no credential generation, shadow_days=0.

    Conflict resolution:
      When a constrained role already has a current MAIN/DEPUTY holder,
      HR must specify what happens to that person on activation day.
      conflict_user + conflict_resolution are populated in that case.
    """

    # ── Status choices ───────────────────────────────────────
    PENDING   = 'PENDING'
    SHADOW    = 'SHADOW'
    ACTIVATED = 'ACTIVATED'
    CANCELLED = 'CANCELLED'

    STATUS_CHOICES = [
        (PENDING,   'Pending'),
        (SHADOW,    'Shadow period active'),
        (ACTIVATED, 'Activated'),
        (CANCELLED, 'Cancelled'),
    ]

    # ── Conflict resolution choices ──────────────────────────
    DEACTIVATE  = 'DEACTIVATE'
    REASSIGN    = 'REASSIGN'
    ROLE_CHANGE = 'ROLE_CHANGE'

    CONFLICT_RESOLUTION_CHOICES = [
        (DEACTIVATE,  'Deactivate'),
        (REASSIGN,    'Reassign to another branch'),
        (ROLE_CHANGE, 'Change role'),
    ]

    # ── Who is being activated ───────────────────────────────
    user = models.OneToOneField(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='pending_activation',
    )

    # Null for existing staff role changes
    applicant = models.ForeignKey(
        'hr.Applicant',
        on_delete=models.PROTECT,
        related_name='activation',
        null=True, blank=True,
    )

    # ── Role being assigned ──────────────────────────────────
    role = models.ForeignKey(
        'accounts.Role',
        on_delete=models.PROTECT,
        related_name='pending_activations',
    )
    designation = models.CharField(
        max_length=10,
        choices=[
            ('MAIN',   'Main'),
            ('DEPUTY', 'Deputy'),
            ('MEMBER', 'Member'),
        ],
        default='MAIN',
    )

    # Organisational unit — mirrors role.scope
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='pending_activations',
        null=True, blank=True,
    )
    region = models.ForeignKey(
        'organization.Region',
        on_delete=models.PROTECT,
        related_name='pending_activations',
        null=True, blank=True,
    )

    # ── Timing ───────────────────────────────────────────────
    start_date  = models.DateField()
    shadow_days = models.IntegerField(
        default=7,
        help_text='Number of days of read-only shadow access before start_date.',
    )

    # ── Conflict resolution ──────────────────────────────────
    # Populated only when a constrained role slot is already occupied
    conflict_user = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='displaced_by_activation',
        null=True, blank=True,
    )
    conflict_resolution = models.CharField(
        max_length=20,
        choices=CONFLICT_RESOLUTION_CHOICES,
        null=True, blank=True,
    )
    # If REASSIGN — which branch the conflict_user moves to
    conflict_new_branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='conflict_reassignments',
        null=True, blank=True,
    )
    # If ROLE_CHANGE — new role and designation for conflict_user
    conflict_new_role = models.ForeignKey(
        'accounts.Role',
        on_delete=models.PROTECT,
        related_name='conflict_role_changes',
        null=True, blank=True,
    )
    conflict_new_designation = models.CharField(
        max_length=10,
        choices=[
            ('MAIN',   'Main'),
            ('DEPUTY', 'Deputy'),
            ('MEMBER', 'Member'),
        ],
        null=True, blank=True,
    )

    # ── Credentials (new hires only) ─────────────────────────
    # temp_password is shown once on creation — stored hashed here,
    # the plaintext is returned in the API response only once and
    # never persisted.
    generated_email    = models.CharField(max_length=255, blank=True)
    generated_username = models.CharField(max_length=100, blank=True)
    temp_password_hash = models.CharField(max_length=255, blank=True)

    # ── Status ───────────────────────────────────────────────
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=PENDING,
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='activations_cancelled',
    )

    # ── Audit ────────────────────────────────────────────────
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='activations_created',
    )

    class Meta:
        ordering = ['start_date']

    def __str__(self):
        return (
            f"Activation: {self.user.full_name} → "
            f"{self.role.display_name} on {self.start_date}"
        )

    @property
    def is_new_hire(self):
        return self.applicant is not None

    @property
    def days_until_start(self):
        from django.utils import timezone
        delta = self.start_date - timezone.localdate()
        return delta.days