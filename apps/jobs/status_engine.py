from django.utils import timezone
from django.db import transaction


# ─────────────────────────────────────────────────────────────────────────────
# Transition Maps
# Format: { current_status: [allowed_next_statuses] }
# ─────────────────────────────────────────────────────────────────────────────

INSTANT_TRANSITIONS = {
    'DRAFT'           : ['PENDING_PAYMENT', 'CANCELLED'],
    'PENDING_PAYMENT' : ['COMPLETE', 'CANCELLED'],
    'COMPLETE'        : [],
    'CANCELLED'       : [],
}

PRODUCTION_TRANSITIONS = {
    'DRAFT'           : ['PENDING_PAYMENT', 'CANCELLED'],
    'PENDING_PAYMENT' : ['PAID', 'CANCELLED'],
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

# Role name as seeded
BRANCH_MANAGER_ROLE = 'BRANCH_MANAGER'


class JobStatusEngine:
    """
    Controls all job status transitions for Octos.

    Rules:
      - Transitions are validated against per-job-type maps
      - Cancellation is blocked once a job reaches PAID or beyond
      - HALTED jobs can only be transitioned by a BRANCH_MANAGER
      - Every transition is logged with actor + timestamp
      - No job status ever changes outside this engine
    """

    def __init__(self, job):
        self.job         = job
        self.transitions = TRANSITION_MAP.get(job.job_type, {})

    # ── Query helpers ────────────────────────────────────────────

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

    # ── Core transition ──────────────────────────────────────────

    @transaction.atomic
    def transition(self, to_status, actor, notes=''):
        """
        Execute a status transition.

        Args:
            to_status : Target status string
            actor     : CustomUser performing the transition
            notes     : Optional notes

        Returns:
            dict with success, from_status, to_status, actor, timestamp

        Raises:
            ValueError  : Illegal transition or insufficient role
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

        JobStatusLog.objects.create(
            job             = self.job,
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

    # ── Class-level shorthand ────────────────────────────────────

    @classmethod
    def advance(cls, job, to_status, actor, notes=''):
        return cls(job).transition(to_status, actor, notes)

    # ── Internal helpers ─────────────────────────────────────────

    @staticmethod
    def _is_branch_manager(actor):
        """Check if actor holds the BRANCH_MANAGER role."""
        try:
            return actor.role.name == BRANCH_MANAGER_ROLE
        except AttributeError:
            return False