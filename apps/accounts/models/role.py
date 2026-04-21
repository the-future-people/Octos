from django.db import models
from apps.core.models import AuditModel


class Permission(AuditModel):
    """
    A single permission codename.
    e.g. 'can_route_job', 'can_confirm_payment'
    """
    codename    = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255)

    def __str__(self):
        return self.codename


class Role(AuditModel):
    """
    A role groups permissions together.
    Every user has exactly one role.

    is_constrained — True means only one MAIN + one DEPUTY
                     may hold this role per organisational unit
                     at any given time (e.g. Branch Manager,
                     Regional Manager, Belt Manager).
                     False means unlimited holders are allowed
                     (e.g. Cashier, Attendant, Designer).

    scope          — Which organisational unit this role belongs to.
                     Drives which FK is set on CustomUser and
                     StaffAssignment when the role is assigned.
                       BRANCH  → user.branch is set
                       REGION  → user.region is set
                       BELT    → neither (Belt-level)
                       HQ      → neither (org-wide)
    """

    SCOPE_BRANCH = 'BRANCH'
    SCOPE_REGION = 'REGION'
    SCOPE_BELT   = 'BELT'
    SCOPE_HQ     = 'HQ'

    SCOPE_CHOICES = [
        (SCOPE_BRANCH, 'Branch'),
        (SCOPE_REGION, 'Region'),
        (SCOPE_BELT,   'Belt'),
        (SCOPE_HQ,     'HQ'),
    ]

    name         = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=100)
    permissions  = models.ManyToManyField(
        Permission,
        blank=True,
        related_name='roles',
    )

    # ── Constraint & scope ───────────────────────────────────
    is_constrained = models.BooleanField(
        default=False,
        help_text=(
            'If True, only one MAIN and one DEPUTY may hold this '
            'role per organisational unit simultaneously.'
        ),
    )
    scope = models.CharField(
        max_length=10,
        choices=SCOPE_CHOICES,
        default=SCOPE_BRANCH,
        help_text='Which organisational unit this role operates within.',
    )

    def __str__(self):
        return self.display_name