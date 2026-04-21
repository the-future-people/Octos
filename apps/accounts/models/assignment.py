from django.db import models
from django.db.models import Q, UniqueConstraint
from apps.core.models import AuditModel


class StaffAssignment(AuditModel):
    """
    The authoritative record of a user's role history.

    Every role change closes the current assignment (is_current=False,
    effective_until=date) and opens a new one. CustomUser.role is a
    denormalised cache that always mirrors the current assignment's role
    for fast permission checks — never update it directly, always go
    through AssignmentService.assign().

    designation:
      MAIN   — the primary holder of a constrained role per unit
      DEPUTY — the secondary holder of a constrained role per unit
      MEMBER — for unconstrained roles (Cashier, Attendant, etc.)
               where MAIN/DEPUTY has no meaning

    For constrained roles (role.is_constrained=True), the DB enforces
    that only one MAIN and one DEPUTY can be current per role+branch
    or role+region simultaneously.
    """

    # ── Designation choices ──────────────────────────────────
    MAIN   = 'MAIN'
    DEPUTY = 'DEPUTY'
    MEMBER = 'MEMBER'

    DESIGNATION_CHOICES = [
        (MAIN,   'Main'),
        (DEPUTY, 'Deputy'),
        (MEMBER, 'Member'),
    ]

    # ── Ended reason choices ─────────────────────────────────
    REASON_PROMOTION   = 'PROMOTION'
    REASON_REPLACEMENT = 'REPLACEMENT'
    REASON_RESIGNATION = 'RESIGNATION'
    REASON_TRANSFER    = 'TRANSFER'
    REASON_DEMOTION    = 'DEMOTION'
    REASON_ACTIVATION  = 'ACTIVATION'

    ENDED_REASON_CHOICES = [
        (REASON_PROMOTION,   'Promotion'),
        (REASON_REPLACEMENT, 'Replacement'),
        (REASON_RESIGNATION, 'Resignation'),
        (REASON_TRANSFER,    'Transfer'),
        (REASON_DEMOTION,    'Demotion'),
        (REASON_ACTIVATION,  'Activation'),
    ]

    # ── Core fields ──────────────────────────────────────────
    user = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='assignments',
    )
    role = models.ForeignKey(
        'accounts.Role',
        on_delete=models.PROTECT,
        related_name='assignments',
    )

    # Organisational unit — one of these is set depending on role.scope.
    # BRANCH scope → branch is set, region is null
    # REGION scope → region is set, branch is null
    # BELT / HQ    → both null
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='staff_assignments',
        null=True, blank=True,
    )
    region = models.ForeignKey(
        'organization.Region',
        on_delete=models.PROTECT,
        related_name='staff_assignments',
        null=True, blank=True,
    )

    designation = models.CharField(
        max_length=10,
        choices=DESIGNATION_CHOICES,
        default=MEMBER,
    )

    # ── Timeline ─────────────────────────────────────────────
    effective_from  = models.DateField()
    effective_until = models.DateField(
        null=True, blank=True,
        help_text='Null means this is the current active assignment.',
    )
    is_current = models.BooleanField(
        default=True,
        db_index=True,
    )

    # ── Closure metadata ─────────────────────────────────────
    ended_reason = models.CharField(
        max_length=20,
        choices=ENDED_REASON_CHOICES,
        null=True, blank=True,
    )
    ended_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assignments_closed',
    )

    class Meta:
        ordering = ['-effective_from']

        constraints = [
            # Only one current MAIN per constrained role per branch
            UniqueConstraint(
                fields=['role', 'branch', 'designation'],
                condition=Q(is_current=True, designation='MAIN', branch__isnull=False),
                name='unique_main_per_role_per_branch',
            ),
            # Only one current DEPUTY per constrained role per branch
            UniqueConstraint(
                fields=['role', 'branch', 'designation'],
                condition=Q(is_current=True, designation='DEPUTY', branch__isnull=False),
                name='unique_deputy_per_role_per_branch',
            ),
            # Only one current MAIN per constrained role per region
            UniqueConstraint(
                fields=['role', 'region', 'designation'],
                condition=Q(is_current=True, designation='MAIN', region__isnull=False),
                name='unique_main_per_role_per_region',
            ),
            # Only one current DEPUTY per constrained role per region
            UniqueConstraint(
                fields=['role', 'region', 'designation'],
                condition=Q(is_current=True, designation='DEPUTY', region__isnull=False),
                name='unique_deputy_per_role_per_region',
            ),
        ]

    def __str__(self):
        unit = self.branch or self.region or 'HQ'
        return (
            f"{self.user.full_name} — {self.role.display_name} "
            f"({self.designation}) @ {unit}"
        )