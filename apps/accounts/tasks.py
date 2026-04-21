import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_staff_activations(self):
    """
    Runs daily at 00:01 WAT.
    Promotes SHADOW employees to ACTIVE when their start_date arrives.
    Executes conflict resolutions (deactivate / reassign / role change)
    on the displaced user.
    Writes audit log entries for every action taken.

    Retries up to 3 times with a 5-minute delay on failure.
    """
    from django.db import transaction
    from apps.accounts.models import CustomUser, PendingActivation, StaffAssignment
    from apps.accounts.assignment_service import AssignmentService

    today = timezone.localdate()
    logger.info(f"[process_staff_activations] Running for date: {today}")

    activations = PendingActivation.objects.filter(
        start_date=today,
        status=PendingActivation.SHADOW,
    ).select_related(
        'user', 'role', 'branch', 'region',
        'conflict_user', 'conflict_new_role', 'conflict_new_branch',
        'created_by',
    )

    if not activations.exists():
        logger.info("[process_staff_activations] No activations due today.")
        return {"activated": 0, "errors": 0}

    activated_count = 0
    error_count     = 0

    for activation in activations:
        try:
            with transaction.atomic():
                _activate_employee(activation, today)
            activated_count += 1
            logger.info(
                f"[process_staff_activations] Activated: "
                f"{activation.user.full_name} → {activation.role.display_name}"
            )
        except Exception as exc:
            error_count += 1
            logger.error(
                f"[process_staff_activations] Failed for activation "
                f"id={activation.id} user={activation.user.full_name}: {exc}",
                exc_info=True,
            )
            # Don't retry the whole task — log and continue to next activation

    logger.info(
        f"[process_staff_activations] Done. "
        f"Activated: {activated_count}, Errors: {error_count}"
    )
    return {"activated": activated_count, "errors": error_count}


def _activate_employee(activation, today):
    """
    Core activation logic — called inside an atomic transaction.
    Promotes the shadow user to ACTIVE, handles the conflict user,
    writes audit events, and marks the activation complete.
    """
    from apps.accounts.models import CustomUser, StaffAssignment
    from apps.accounts.assignment_service import AssignmentService
    from apps.analytics.models import AuditEvent

    user = activation.user

    # ── 1. Promote shadow user → ACTIVE ──────────────────────
    AssignmentService.assign(
        user           = user,
        role           = activation.role,
        designation    = activation.designation,
        branch         = activation.branch,
        region         = activation.region,
        effective_from = today,
        acted_by       = activation.created_by,
        ended_reason   = StaffAssignment.REASON_ACTIVATION,
        force          = True,  # conflict was already resolved at verify time
    )

    user.employment_status    = CustomUser.ACTIVE
    user.must_change_password = True  # force password change on first real login
    user.save(update_fields=['employment_status', 'must_change_password', 'updated_at'])

    # ── 2. Handle conflict user ───────────────────────────────
    if activation.conflict_user and activation.conflict_resolution:
        _resolve_conflict(activation, today)

    # ── 3. Mark activation complete ──────────────────────────
    activation.status       = PendingActivation.ACTIVATED
    activation.activated_at = timezone.now()
    activation.save(update_fields=['status', 'activated_at', 'updated_at'])

    # ── 4. Write audit log ────────────────────────────────────
    _write_activation_audit(activation, today)

    # ── 5. Send notifications ─────────────────────────────────
    _notify_activation(activation)


def _resolve_conflict(activation, today):
    """
    Execute the conflict resolution action on the displaced user.
    Called inside the same atomic transaction as _activate_employee.
    """
    from apps.accounts.models import CustomUser, StaffAssignment
    from apps.accounts.assignment_service import AssignmentService

    conflict_user = activation.conflict_user
    resolution    = activation.conflict_resolution

    if resolution == PendingActivation.DEACTIVATE:
        AssignmentService.deactivate(
            user           = conflict_user,
            acted_by       = activation.created_by,
            effective_until= today,
        )
        logger.info(
            f"[_resolve_conflict] Deactivated: {conflict_user.full_name}"
        )

    elif resolution == PendingActivation.REASSIGN:
        if not activation.conflict_new_branch:
            raise ValueError(
                f"REASSIGN resolution for activation {activation.id} "
                f"has no conflict_new_branch set."
            )
        AssignmentService.assign(
            user           = conflict_user,
            role           = conflict_user.role,
            designation    = StaffAssignment.MAIN,
            branch         = activation.conflict_new_branch,
            region         = None,
            effective_from = today,
            acted_by       = activation.created_by,
            ended_reason   = StaffAssignment.REASON_TRANSFER,
            force          = True,
        )
        logger.info(
            f"[_resolve_conflict] Reassigned: {conflict_user.full_name} "
            f"→ {activation.conflict_new_branch.name}"
        )

    elif resolution == PendingActivation.ROLE_CHANGE:
        if not activation.conflict_new_role:
            raise ValueError(
                f"ROLE_CHANGE resolution for activation {activation.id} "
                f"has no conflict_new_role set."
            )
        new_designation = activation.conflict_new_designation or StaffAssignment.MEMBER
        AssignmentService.assign(
            user           = conflict_user,
            role           = activation.conflict_new_role,
            designation    = new_designation,
            branch         = conflict_user.branch,
            region         = conflict_user.region,
            effective_from = today,
            acted_by       = activation.created_by,
            ended_reason   = StaffAssignment.REASON_DEMOTION,
            force          = True,
        )
        logger.info(
            f"[_resolve_conflict] Role changed: {conflict_user.full_name} "
            f"→ {activation.conflict_new_role.display_name}"
        )


def _write_activation_audit(activation, today):
    """Write an audit event for the completed activation."""
    try:
        from apps.analytics.signals.handlers import _write_event
        _write_event(
            event_type  = 'EMPLOYEE_ACTIVATED',
            severity    = 'INFO',
            user        = activation.created_by,
            branch      = activation.branch,
            entity_type = 'PendingActivation',
            entity_id   = activation.id,
            metadata    = {
                'activated_user'  : activation.user.full_name,
                'activated_email' : activation.user.email,
                'role'            : activation.role.display_name,
                'designation'     : activation.designation,
                'start_date'      : str(today),
                'conflict_user'   : (
                    activation.conflict_user.full_name
                    if activation.conflict_user else None
                ),
                'conflict_resolution': activation.conflict_resolution or None,
            },
        )
    except Exception as exc:
        # Audit failure must never break activation
        logger.warning(f"[_write_activation_audit] Audit write failed: {exc}")


def _notify_activation(activation):
    """
    Send in-app notifications to the activated user and the conflict user.
    WhatsApp deferred to Phase 7.
    """
    try:
        from apps.notifications.services import NotificationService
        NotificationService.notify(
            user    = activation.user,
            title   = 'You are now active!',
            message = (
                f'Your account is now fully active as '
                f'{activation.role.display_name}. '
                f'Welcome to the team.'
            ),
        )
        if activation.conflict_user:
            NotificationService.notify(
                user    = activation.conflict_user,
                title   = 'Role update',
                message = (
                    f'Your role has been updated as of {activation.start_date}. '
                    f'Please contact HR if you have any questions.'
                ),
            )
    except Exception as exc:
        # Notification failure must never break activation
        logger.warning(f"[_notify_activation] Notification failed: {exc}")