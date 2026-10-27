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

    # ── Halts ────────────────────────────────────────────────────

    @transaction.atomic
    def halt(self, reason, actor, note=''):
        """
        Stop work on a job. A halt is a condition, not a place — the work
        state is left exactly as it is, so resuming restores the stage the
        job was actually in rather than a remembered guess.

        The Coordinator halts and resumes freely: they are closest to the
        work, and requiring permission means jobs sit idle.
        """
        from apps.jobs.models import JobHalt

        # An assigned operator may stop a job on their machine for what
        # they can see from there: the machine, the file, the material.
        operator_reason = reason in ('MACHINE_BREAKDOWN', 'FILE_FAULT', 'MATERIALS_OUT')
        if not (self._may_move_axis('WORK', actor)
                or (operator_reason and self._operates_this_job(actor))):
            raise PermissionError(
                f"{actor.full_name or actor.email} cannot halt "
                f"{self.job.job_number}."
            )

        if self.active_halt():
            raise ValueError(f"{self.job.job_number} is already halted.")

        if self.job.work_state == 'DONE':
            raise ValueError(
                f"{self.job.job_number} is already finished — nothing to halt."
            )

        return JobHalt.objects.create(
            job                = self.job,
            reason             = reason,
            note               = note,
            work_state_at_halt = self.job.work_state,
            halted_by          = actor,
        )

    @transaction.atomic
    def resume(self, actor):
        """
        Resume the active halt. The work state was never overwritten, so
        there is nothing to restore — closing the record is the whole
        operation.
        """
        if not self._may_move_axis('WORK', actor):
            raise PermissionError(
                f"{actor.full_name or actor.email} cannot resume "
                f"{self.job.job_number}."
            )

        halt = self.active_halt()
        if not halt:
            raise ValueError(f"{self.job.job_number} is not halted.")

        halt.resumed_at = timezone.now()
        halt.resumed_by = actor
        halt.save(update_fields=['resumed_at', 'resumed_by', 'updated_at'])
        return halt

    def active_halt(self):
        """The open halt on this job, or None."""
        return self.job.halts.filter(resumed_at__isnull=True).first()

    def is_halted(self) -> bool:
        return self.active_halt() is not None

    # ── Verification ─────────────────────────────────────────────

    @transaction.atomic
    def verify(self, actor, note='', customer_contacted=False,
               customer_response=''):
        """
        Clear a remote order for production.

        The coordinator's job: open the file, read the spec, decide whether
        it can be made as ordered. A walk-in never reaches here — the
        customer was standing there and anything unclear was asked on the
        spot.
        """
        from apps.jobs.models import JobVerification

        if not self._may_move_axis('WORK', actor):
            raise PermissionError(
                f"{actor.full_name or actor.email} cannot verify "
                f"{self.job.job_number}."
            )

        if not self.job.needs_verification:
            raise ValueError(
                f"{self.job.job_number} came in at the counter and needs "
                f"no verification."
            )

        if self.job.is_verified:
            raise ValueError(
                f"{self.job.job_number} has already been cleared."
            )

        verification = JobVerification.objects.create(
            job                = self.job,
            outcome            = JobVerification.Outcome.PASSED,
            note               = note,
            customer_contacted = customer_contacted,
            customer_response  = customer_response,
            checked_by         = actor,
        )

        # Cleared means in press. A job left at RECEIVED after clearing
        # told the customer it was still being inspected and showed the
        # coordinator a second "Start" to press. Moved through move_work
        # so the status log records it: tracking builds the customer's
        # timeline from that log, and timing learns from it.
        #
        # Not when it cannot be made yet. Instant work has no press stage,
        # and a remote order cleared before its deposit waits at RECEIVED
        # for the cashier, as it always has. Stated explicitly rather than
        # attempted and caught, so a real failure raises instead of being
        # skipped in silence.
        #
        # Every coordinator view loads jobs with their verifications
        # prefetched, and is_verified reads that cached list, which was
        # taken before this verification existed. Without dropping it the
        # move below sees "not verified" and refuses, and the atomic block
        # rolls the whole clear back. Naming the relation clears only its
        # prefetch, not the rest of the job.
        self.job.refresh_from_db(fields=['verifications'])

        can_start = (
            self.job.job_type != 'INSTANT'
            and self.job.payment_state != 'UNPAID'
        )
        if can_start:
            self.move_work('IN_PRODUCTION', actor, notes='Cleared for production')

            # Each line's route becomes its steps, each step is given a
            # machine, and whatever can start does. Inside the same
            # transaction: a job is never in press with no steps.
            from apps.jobs.services.steps import build_steps, sync_stage
            build_steps(self.job)
            sync_stage(self.job, actor)

        return verification

    @transaction.atomic
    def reject_verification(self, outcome, actor, note='',
                            customer_contacted=False, customer_response=''):
        """
        Record that a remote order cannot proceed as sent.

        Deliberately does not halt the job. Halting is the coordinator's
        own act — it makes the state visible before anyone picks up the
        phone, and some problems need no call at all. Coupling the two
        would take that judgement away.
        """
        from apps.jobs.models import JobVerification

        if not self._may_move_axis('WORK', actor):
            raise PermissionError(
                f"{actor.full_name or actor.email} cannot verify "
                f"{self.job.job_number}."
            )

        if outcome == JobVerification.Outcome.PASSED:
            raise ValueError('Use verify() to clear a job.')

        return JobVerification.objects.create(
            job                = self.job,
            outcome            = outcome,
            note               = note,
            customer_contacted = customer_contacted,
            customer_response  = customer_response,
            checked_by         = actor,
        )

    # ── Core axis transition ─────────────────────────────────────

    @transaction.atomic
    def _move_axis(self, axis, axis_map, to_state, actor, notes=''):
        from apps.jobs.models import JobStatusLog

        field      = AXIS_FIELD[axis]
        from_state = getattr(self.job, field)

        # Guard: role owns this axis, or this is the one move an operator makes
        if not (self._may_move_axis(axis, actor)
                or self._operator_may_move(axis, from_state, to_state, actor)):
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

        # Guard: a halted job cannot move on the work axis. Payment and
        # handover are unaffected — a customer can still settle a balance
        # while the machine is down.
        if axis == 'WORK' and self.is_halted():
            raise ValueError(
                f"{self.job.job_number} is halted. Resume it before "
                f"moving the work forward."
            )

        # Guard: cross-axis rules
        block = self._cross_axis_block(axis, to_state)
        if block:
            raise ValueError(block)

        now = timezone.now()
        setattr(self.job, field, to_state)
        update_fields = [field, 'updated_at']

        # When the work began, which is a different question from when
        # the job arrived. An estimate missed because the job queued for
        # a day is a different failure from one missed because the work
        # took longer than thought, and only both timestamps tell them
        # apart.
        #
        # Set once. A job reaching finishing has not started twice, and
        # a resumed job began when it began.
        if (
            axis == 'WORK'
            and to_state == 'IN_PRODUCTION'
            and self.job.work_started_at is None
        ):
            self.job.work_started_at = now
            update_fields.append('work_started_at')

        # Materials are consumed when the work finishes, not when the
        # customer walks in — so deduction belongs on the work axis.
        if axis == 'WORK' and to_state == 'DONE':
            self._deduct_inventory(actor)

            # The customer is told once the move has committed, and from
            # the worker rather than this request: a rolled-back move must
            # not text anyone, and the coordinator's tap must not wait on
            # mNotify. DONE is terminal on the work axis, so this fires
            # once per job. Imported here so jobs does not load storefront
            # at module import.
            from apps.storefront.tasks import tell_customer_ready
            job_id = self.job.pk
            transaction.on_commit(lambda: tell_customer_ready.delay(job_id))
            # Ready: was the promise kept? Scored against the first one.
            from apps.jobs.services.lateness import record_outcome
            record_outcome(self.job)

        # Every move nudges the customer's app to refresh, silently, after
        # the move is saved. Counter jobs have no app; the task finds that.
        from apps.storefront.tasks import nudge_app
        from apps.jobs.tasks import check_promise
        nudged_job = self.job.pk
        transaction.on_commit(lambda: nudge_app.delay(nudged_job))
        # And look at its promise again, now the floor has changed.
        transaction.on_commit(lambda: check_promise.delay(nudged_job))

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
            # Nobody at the branch has looked at what was sent. Printing
            # five hundred flyers from an unopened file is how a customer
            # gets a refund and the branch eats the stock.
            if job.needs_verification and not job.is_verified:
                return (
                    f"{job.job_number} has not been verified. A coordinator "
                    f"must check the file and specification first."
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

    def _operator_may_move(self, axis, from_state, to_state, actor):
        """
        The one move an operator makes: printing is finished, so the job
        goes to Finishing. Allowed by assignment, not role, since whoever
        runs a machine may be an attendant one month and a technician the
        next. Only someone currently assigned to a machine this job has a
        step on, and only this move.
        """
        if (axis, from_state, to_state) != ('WORK', 'IN_PRODUCTION', 'FINISHING'):
            return False
        return self._operates_this_job(actor)

    def _operates_this_job(self, actor):
        """Currently assigned to a machine this job has a step on."""
        if actor is None or not getattr(actor, 'is_active', False):
            return False
        from apps.production.models import MachineOperator
        return MachineOperator.objects.filter(
            operator=actor, active_until__isnull=True,
            machine__job_steps__job=self.job,
        ).exists()

    @classmethod
    def _is_branch_manager(cls, actor):
        """Check if actor holds the BRANCH_MANAGER role."""
        return cls._role_name(actor) == BRANCH_MANAGER_ROLE