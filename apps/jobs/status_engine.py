from django.utils import timezone
from django.db import transaction


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY status maps — still authoritative for every unmigrated callsite.
# Format: { current_status: [allowed_next_statuses] }
#
# These stay until step 4 moves the last reader onto the axes below.
# ─────────────────────────────────────────────────────────────────────────────

INSTANT_TRANSITIONS = {
    'DRAFT'           : ['PENDING_PAYMENT', 'CANCELLED'],
    'PENDING_PAYMENT' : ['COMPLETE', 'CANCELLED'],
    'INTAKE_HELD'     : ['PENDING_PAYMENT'],  # morning handover affirmed by cashier
    'COMPLETE'        : [],
    'CANCELLED'       : [],
}

PRODUCTION_TRANSITIONS = {
    'DRAFT'           : ['PENDING_PAYMENT', 'CANCELLED'],
    'PENDING_PAYMENT' : ['PAID', 'CANCELLED'],
    'INTAKE_HELD'     : ['PENDING_PAYMENT'],  # morning handover affirmed by cashier
    'PAID'            : ['CONFIRMED'],
    'CONFIRMED'       : ['IN_PROGRESS'],
    'IN_PROGRESS'     : ['READY', 'HALTED'],
    'READY'           : ['OUT_FOR_DELIVERY', 'COMPLETE'],
    'OUT_FOR_DELIVERY': ['COMPLETE'],
    'HALTED'          : ['IN_PROGRESS', 'CANCELLED'],  # BRANCH_MANAGER only
    'COMPLETE'        : [],
    'CANCELLED'       : [],
}

DESIGN_TRANSITIONS = {
    'DRAFT'              : ['PENDING_PAYMENT', 'CANCELLED'],
    'PENDING_PAYMENT'    : ['PAID', 'CANCELLED'],
    'INTAKE_HELD'        : ['PENDING_PAYMENT'],  # morning handover affirmed by cashier
    'PAID'               : ['IN_PROGRESS'],
    'IN_PROGRESS'        : ['SAMPLE_SENT', 'HALTED'],
    'SAMPLE_SENT'        : ['REVISION_REQUESTED', 'DESIGN_APPROVED'],
    'REVISION_REQUESTED' : ['IN_PROGRESS'],
    'DESIGN_APPROVED'    : ['READY'],
    'READY'              : ['OUT_FOR_DELIVERY', 'COMPLETE'],
    'OUT_FOR_DELIVERY'   : ['COMPLETE'],
    'HALTED'             : ['IN_PROGRESS', 'CANCELLED'],  # BRANCH_MANAGER only
    'COMPLETE'           : [],
    'CANCELLED'          : [],
}

TRANSITION_MAP = {
    'INSTANT'    : INSTANT_TRANSITIONS,
    'PRODUCTION' : PRODUCTION_TRANSITIONS,
    'DESIGN'     : DESIGN_TRANSITIONS,
}

# Statuses that cannot be cancelled from (by anyone)
NO_CANCEL_AFTER = {'PAID', 'CONFIRMED', 'IN_PROGRESS', 'READY',
                   'SAMPLE_SENT', 'REVISION_REQUESTED', 'DESIGN_APPROVED',
                   'OUT_FOR_DELIVERY', 'COMPLETE'}

# Statuses that require BRANCH_MANAGER role to transition out of
MANAGER_ONLY_STATUSES = {'HALTED'}


# ─────────────────────────────────────────────────────────────────────────────
# AXIS maps — the lifecycle rebuild.
#
# Job.status conflates three unrelated facts: where the money is, where the
# physical work is, and whether the customer has the goods. One value cannot
# express a job that is part-paid, in production, and awaiting collection.
# ─────────────────────────────────────────────────────────────────────────────

PAYMENT_TRANSITIONS = {
    'UNPAID'       : ['DEPOSIT_PAID', 'SETTLED'],
    'DEPOSIT_PAID' : ['SETTLED'],
    'SETTLED'      : [],
}

# Instant work is finished before the cashier ever sees it — there are no
# intermediate stages to record.
WORK_TRANSITIONS_INSTANT = {
    'RECEIVED' : ['DONE'],
    'DONE'     : [],
}

# FINISHING and QUALITY_CHECK are separate states deliberately: finishing
# quality is the intended commercial differentiator, and an untracked stage
# cannot be measured.
WORK_TRANSITIONS_PRODUCTION = {
    'RECEIVED'      : ['IN_PRODUCTION'],
    'IN_PRODUCTION' : ['FINISHING'],
    'FINISHING'     : ['QUALITY_CHECK'],
    'QUALITY_CHECK' : ['DONE'],
    'DONE'          : [],
}

WORK_TRANSITION_MAP = {
    'INSTANT'    : WORK_TRANSITIONS_INSTANT,
    'PRODUCTION' : WORK_TRANSITIONS_PRODUCTION,
    'DESIGN'     : WORK_TRANSITIONS_PRODUCTION,
}

HANDOVER_TRANSITIONS = {
    'AWAITING_COLLECTION' : ['OUT_FOR_DELIVERY', 'HANDED_OVER'],
    'OUT_FOR_DELIVERY'    : ['HANDED_OVER'],
    'HANDED_OVER'         : [],
}

AXIS_FIELD = {
    'PAYMENT'  : 'payment_state',
    'WORK'     : 'work_state',
    'HANDOVER' : 'handover_state',
}

# ── Roles ────────────────────────────────────────────────────────
BRANCH_MANAGER_ROLE = 'BRANCH_MANAGER'
CASHIER_ROLE        = 'CASHIER'
ATTENDANT_ROLE      = 'ATTENDANT'
COORDINATOR_ROLE    = 'FLOW_COORDINATOR'

# Separation of duties: no single person can create a job, produce it, take
# the money and release the goods. Fail-closed — a role absent from this map
# owns nothing.
AXIS_OWNERS = {
    'PAYMENT'  : {CASHIER_ROLE},
    'WORK'     : {COORDINATOR_ROLE},
    'HANDOVER' : {ATTENDANT_ROLE},
}

# Roles that may move any axis. Deliberately small.
AXIS_OVERRIDE_ROLES = {BRANCH_MANAGER_ROLE, 'REGIONAL_MANAGER',
                       'BELT_MANAGER', 'SUPER_ADMIN'}


class JobStatusEngine:
    """
    Controls all job state transitions for Octos.

    Two APIs live here during the lifecycle migration:

      LEGACY  — transition() / advance(), driving Job.status.
                Unchanged. Every existing callsite still uses it.

      AXIS    — move_payment() / move_work() / move_handover(), driving
                payment_state, work_state and handover_state independently.
                Each also rewrites Job.status via _derive_legacy_status()
                so unmigrated readers stay correct.

    Job.status is retained and written by both. It is removed only when the
    last reader has migrated.
    """

    def __init__(self, job):
        self.job         = job
        self.transitions = TRANSITION_MAP.get(job.job_type, {})

    # ═════════════════════════════════════════════════════════════
    # LEGACY API — untouched
    # ═════════════════════════════════════════════════════════════

    def can_transition(self, to_status, actor=None):
        """
        Check if transition is valid.
        Optionally pass actor to enforce role-based guards.
        """
        allowed = self.transitions.get(self.job.status, [])
        if to_status not in allowed:
            return False

        # HALTED → any: only BRANCH_MANAGER
        if self.job.status in MANAGER_ONLY_STATUSES:
            if actor is None:
                return False
            if not self._is_branch_manager(actor):
                return False

        return True

    def get_allowed_transitions(self, actor=None):
        """
        Returns list of statuses this job can legally move to.
        Pass actor to filter by role-based guards.
        """
        raw = self.transitions.get(self.job.status, [])
        if actor is None:
            return raw
        return [s for s in raw if self.can_transition(s, actor=actor)]

    @transaction.atomic
    def transition(self, to_status, actor, notes=''):
        """
        Execute a legacy status transition.

        Args:
            to_status : Target status string
            actor     : CustomUser performing the transition
            notes     : Optional notes

        Returns:
            dict with success, from_status, to_status, actor, timestamp

        Raises:
            ValueError      : Illegal transition
            PermissionError : Actor lacks required role
        """
        from apps.jobs.models import JobStatusLog

        # Guard: cancellation blocked after PAID
        if to_status == 'CANCELLED' and self.job.status in NO_CANCEL_AFTER:
            raise ValueError(
                f"Cannot cancel {self.job.job_number} — "
                f"job has already been paid. Contact a Branch Manager."
            )

        # Guard: HALTED transitions require BRANCH_MANAGER
        if self.job.status in MANAGER_ONLY_STATUSES:
            if not self._is_branch_manager(actor):
                raise PermissionError(
                    f"Only a Branch Manager can move a halted job. "
                    f"({actor.full_name or actor.email} is not authorised)"
                )

        # Guard: valid transition
        allowed = self.transitions.get(self.job.status, [])
        if to_status not in allowed:
            raise ValueError(
                f"Cannot transition {self.job.job_number} "
                f"from '{self.job.status}' to '{to_status}'. "
                f"Allowed: {allowed}"
            )

        from_status = self.job.status
        now         = timezone.now()

        self.job.status = to_status
        self.job.save(update_fields=['status', 'updated_at'])

        # ── Auto-deduct inventory on job completion ───────────────────
        if to_status == 'COMPLETE':
            self._deduct_inventory(actor)

        JobStatusLog.objects.create(
            job             = self.job,
            axis            = JobStatusLog.Axis.RECORD,
            from_status     = from_status,
            to_status       = to_status,
            actor           = actor,
            notes           = notes,
            transitioned_at = now,
        )

        return {
            'success'     : True,
            'job_number'  : self.job.job_number,
            'from_status' : from_status,
            'to_status'   : to_status,
            'actor'       : actor.full_name or actor.email,
            'timestamp'   : now.isoformat(),
        }

    @classmethod
    def advance(cls, job, to_status, actor, notes=''):
        return cls(job).transition(to_status, actor, notes)

    # ═════════════════════════════════════════════════════════════
    # AXIS API
    # ═════════════════════════════════════════════════════════════

    def move_payment(self, to_state, actor, notes=''):
        """Cashier only. The single place money state ever changes."""
        return self._move_axis('PAYMENT', PAYMENT_TRANSITIONS,
                               to_state, actor, notes)

    def move_work(self, to_state, actor, notes=''):
        """Flow Coordinator only. Back room; never meets a customer."""
        work_map = WORK_TRANSITION_MAP.get(self.job.job_type, {})
        return self._move_axis('WORK', work_map, to_state, actor, notes)

    def move_handover(self, to_state, actor, notes=''):
        """Attendant only. The customer-facing release of goods."""
        return self._move_axis('HANDOVER', HANDOVER_TRANSITIONS,
                               to_state, actor, notes)

    def get_allowed_axis_moves(self, axis, actor=None):
        """Legal next states on one axis, filtered by the actor's role."""
        axis     = axis.upper()
        axis_map = self._map_for(axis)
        current  = getattr(self.job, AXIS_FIELD[axis], None)
        raw      = axis_map.get(current, [])

        if actor is not None and not self._may_move_axis(axis, actor):
            return []

        return [s for s in raw if not self._cross_axis_block(axis, s)]

    # ── Core axis transition ─────────────────────────────────────

    @transaction.atomic
    def _move_axis(self, axis, axis_map, to_state, actor, notes=''):
        from apps.jobs.models import JobStatusLog

        field      = AXIS_FIELD[axis]
        from_state = getattr(self.job, field)

        # Guard: role owns this axis
        if not self._may_move_axis(axis, actor):
            raise PermissionError(
                f"{actor.full_name or actor.email} cannot move the "
                f"{axis.lower()} state of {self.job.job_number}."
            )

        # Guard: legal step on this axis
        allowed = axis_map.get(from_state, [])
        if to_state not in allowed:
            raise ValueError(
                f"Cannot move {self.job.job_number} {axis.lower()} "
                f"from '{from_state}' to '{to_state}'. Allowed: {allowed}"
            )

        # Guard: cross-axis rules
        block = self._cross_axis_block(axis, to_state)
        if block:
            raise ValueError(block)

        now = timezone.now()
        setattr(self.job, field, to_state)
        update_fields = [field, 'updated_at']

        # Materials are consumed when the work finishes, not when the
        # customer walks in — so deduction belongs on the work axis.
        if axis == 'WORK' and to_state == 'DONE':
            self._deduct_inventory(actor)

        if axis == 'HANDOVER' and to_state == 'HANDED_OVER':
            self.job.handed_over_at = now
            self.job.handed_over_by = actor
            update_fields += ['handed_over_at', 'handed_over_by']

        legacy = self._derive_legacy_status()
        if legacy and legacy != self.job.status:
            self.job.status = legacy
            update_fields.append('status')

        self.job.save(update_fields=update_fields)

        JobStatusLog.objects.create(
            job             = self.job,
            axis            = axis,
            from_status     = from_state,
            to_status       = to_state,
            actor           = actor,
            notes           = notes,
            transitioned_at = now,
        )

        return {
            'success'     : True,
            'job_number'  : self.job.job_number,
            'axis'        : axis,
            'from_state'  : from_state,
            'to_state'    : to_state,
            'status'      : self.job.status,
            'actor'       : actor.full_name or actor.email,
            'timestamp'   : now.isoformat(),
        }

    # ── Cross-axis rules ─────────────────────────────────────────

    def _cross_axis_block(self, axis, to_state):
        """
        The only place axes are allowed to consult each other.
        Returns a human-readable reason string, or None if permitted.
        """
        job = self.job

        if axis == 'HANDOVER' and to_state in ('OUT_FOR_DELIVERY', 'HANDED_OVER'):
            if job.work_state != 'DONE':
                return (
                    f"{job.job_number} is not finished yet — "
                    f"work is at {job.work_state}."
                )
            # An attendant can never release an unpaid job. The balance may
            # sit on an approved credit account, but only the cashier puts
            # it there: it is a money decision.
            if job.payment_state != 'SETTLED' and not job.credit_account_id:
                return (
                    f"{job.job_number} has a balance outstanding. "
                    f"Send the customer to the cashier before releasing."
                )

        if axis == 'WORK' and to_state == 'IN_PRODUCTION':
            # Instant work is already finished before the cashier sees it,
            # so this rule applies only to job types that queue.
            if job.job_type != 'INSTANT' and job.payment_state == 'UNPAID':
                return (
                    f"{job.job_number} has no deposit — "
                    f"production cannot start until the cashier takes payment."
                )

        return None

    # ── Legacy status derivation ─────────────────────────────────

    def _derive_legacy_status(self):
        """
        Keeps Job.status truthful for readers that have not migrated yet.
        Deliberately one function, in one place, so there is a single thing
        to delete when the last reader is gone.

        Returns None to leave status alone — record states (DRAFT,
        INTAKE_HELD, CANCELLED) are not expressible on any axis and must
        never be overwritten by an axis move.
        """
        job = self.job

        if job.status in ('DRAFT', 'INTAKE_HELD', 'CANCELLED'):
            return None

        if job.handover_state == 'HANDED_OVER':
            return 'COMPLETE'
        if job.handover_state == 'OUT_FOR_DELIVERY':
            return 'OUT_FOR_DELIVERY'
        if job.work_state == 'DONE':
            return 'READY'
        if job.work_state in ('IN_PRODUCTION', 'FINISHING', 'QUALITY_CHECK'):
            return 'IN_PROGRESS'
        if job.payment_state in ('DEPOSIT_PAID', 'SETTLED'):
            return 'PAID'
        return None

    # ── Internal helpers ─────────────────────────────────────────

    def _map_for(self, axis):
        if axis == 'PAYMENT':
            return PAYMENT_TRANSITIONS
        if axis == 'WORK':
            return WORK_TRANSITION_MAP.get(self.job.job_type, {})
        if axis == 'HANDOVER':
            return HANDOVER_TRANSITIONS
        return {}

    def _deduct_inventory(self, actor):
        try:
            from apps.inventory.inventory_engine import InventoryEngine
            InventoryEngine(self.job.branch).deduct_for_job(
                job   = self.job,
                actor = actor,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'InventoryEngine: auto-deduction failed for job %s',
                self.job.job_number,
            )
            # Never block the job — inventory is non-critical

    @staticmethod
    def _role_name(actor):
        return getattr(getattr(actor, 'role', None), 'name', '') or ''

    @classmethod
    def _may_move_axis(cls, axis, actor):
        """Fail-closed: an unrecognised role owns nothing."""
        role = cls._role_name(actor)
        if not role:
            return False
        if role in AXIS_OVERRIDE_ROLES:
            return True
        return role in AXIS_OWNERS.get(axis, set())

    @classmethod
    def _is_branch_manager(cls, actor):
        """Check if actor holds the BRANCH_MANAGER role."""
        return cls._role_name(actor) == BRANCH_MANAGER_ROLE