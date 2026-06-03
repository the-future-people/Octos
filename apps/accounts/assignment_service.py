from django.db import transaction
from django.utils import timezone

from apps.accounts.models import CustomUser, StaffAssignment, PendingActivation


class ConflictError(Exception):
    """
    Raised when a constrained role slot is already occupied and no
    conflict resolution has been specified.
    """
    def __init__(self, existing_assignment):
        self.existing_assignment = existing_assignment
        super().__init__(
            f"Role slot already occupied by {existing_assignment.user.full_name}"
        )


class AssignmentService:
    """
    The single entry point for all role changes in Octos.

    Never update CustomUser.role, CustomUser.branch, or CustomUser.region
    directly. Always go through this service so that:
      - StaffAssignment history is maintained
      - CustomUser denormalised fields stay in sync
      - Constrained role conflicts are detected before they hit the DB
      - All changes happen atomically

    Public methods
    ──────────────
    assign()          — assign a role to a user (closes current, opens new)
    check_conflict()  — check if a constrained slot is occupied (read-only)
    close_current()   — close a user's current assignment without opening a new one
    """

    @staticmethod
    def check_conflict(role, designation, branch=None, region=None, exclude_user=None):
        """
        Check whether a constrained role slot is already occupied.

        Returns the conflicting StaffAssignment if one exists, else None.
        Only meaningful when role.is_constrained=True and designation
        is MAIN or DEPUTY.

        exclude_user — optionally exclude a specific user from the check
        (used when reassigning the same user to a new designation).
        """
        if not role.is_constrained:
            return None
        if designation == StaffAssignment.MEMBER:
            return None

        qs = StaffAssignment.objects.filter(
            role=role,
            designation=designation,
            is_current=True,
        )

        if branch is not None:
            qs = qs.filter(branch=branch)
        elif region is not None:
            qs = qs.filter(region=region)
        else:
            # Belt / HQ scope — no unit filter
            qs = qs.filter(branch__isnull=True, region__isnull=True)

        if exclude_user is not None:
            qs = qs.exclude(user=exclude_user)

        return qs.select_related('user', 'role').first()

    @staticmethod
    @transaction.atomic
    def assign(
        user,
        role,
        designation,
        effective_from,
        acted_by,
        branch=None,
        region=None,
        ended_reason=StaffAssignment.REASON_ACTIVATION,
        force=False,
    ):
        """
        Assign a role to a user.

        Steps:
          1. Conflict check (raises ConflictError if slot occupied and force=False)
          2. Close user's current StaffAssignment if one exists
          3. Update CustomUser denormalised fields atomically
          4. Open new StaffAssignment
          5. Return the new StaffAssignment

        Parameters
        ──────────
        user            — CustomUser being assigned
        role            — Role being assigned
        designation     — MAIN / DEPUTY / MEMBER
        effective_from  — date the assignment takes effect
        acted_by        — CustomUser performing the action (for audit)
        branch          — Branch FK (for BRANCH scope roles)
        region          — Region FK (for REGION scope roles)
        ended_reason    — reason code written to the closed assignment
        force           — if True, skip conflict check (use only in Celery
                          task where conflict has already been resolved)
        """
        if not force:
            conflict = AssignmentService.check_conflict(
                role=role,
                designation=designation,
                branch=branch,
                region=region,
                exclude_user=user,
            )
            if conflict:
                raise ConflictError(conflict)

        # ── 1. Close current assignment ──────────────────────
        AssignmentService.close_current(
            user=user,
            effective_until=effective_from,
            ended_reason=ended_reason,
            ended_by=acted_by,
        )

        # ── 2. Sync CustomUser denormalised fields ───────────
        user.role   = role
        user.branch = branch
        user.region = region
        user.save(update_fields=['role', 'branch', 'region', 'updated_at'])

        # ── 3. Open new assignment ───────────────────────────
        new_assignment = StaffAssignment.objects.create(
            user=user,
            role=role,
            designation=designation,
            branch=branch,
            region=region,
            effective_from=effective_from,
            is_current=True,
        )

        return new_assignment

    @staticmethod
    @transaction.atomic
    def close_current(user, effective_until, ended_reason, ended_by):
        """
        Close a user's current StaffAssignment.
        Safe to call even if no current assignment exists (no-op).
        """
        StaffAssignment.objects.filter(
            user=user,
            is_current=True,
        ).update(
            is_current=False,
            effective_until=effective_until,
            ended_reason=ended_reason,
            ended_by=ended_by,
            updated_at=timezone.now(),
        )

    @staticmethod
    @transaction.atomic
    def deactivate(user, acted_by, effective_until):
        """
        Deactivate a user entirely.
        Closes their current assignment, sets employment_status=INACTIVE,
        and disables login (is_active=False).
        """
        AssignmentService.close_current(
            user=user,
            effective_until=effective_until,
            ended_reason=StaffAssignment.REASON_RESIGNATION,
            ended_by=acted_by,
        )
        user.is_active = False
        user.employment_status = CustomUser.INACTIVE
        user.role   = None
        user.branch = None
        user.region = None
        user.save(update_fields=[
            'is_active', 'employment_status',
            'role', 'branch', 'region', 'updated_at',
        ])