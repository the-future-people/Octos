"""
Taking a machine down and bringing it back.

A machine going down halts everything queued on it. That is deliberately
blunt: over-halting is visible and a coordinator can resume what can
actually move to another station, whereas under-halting means a job sits
waiting on a machine nobody knows is broken.

The reasons are a short list with a free-text fallback. The list should
grow from what actually gets typed into that fallback — a guessed taxonomy
is worse than one learned from a year of breakdowns.
"""

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Roles that may mark a machine down. The coordinator lives with the
# machines and is the one affected; making them find a manager first means
# the system lags the floor by however long that takes.
MACHINE_STATE_ROLES = {
    'FLOW_COORDINATOR', 'BRANCH_MANAGER',
    'REGIONAL_MANAGER', 'BELT_MANAGER', 'SUPER_ADMIN',
}


class MachineService:

    @staticmethod
    def _may_change_state(actor) -> bool:
        role = getattr(getattr(actor, 'role', None), 'name', '') or ''
        return role in MACHINE_STATE_ROLES

    # ── Taking it down ───────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def mark_down(cls, machine, reason, actor, note='') -> dict:
        """
        Take a machine out of service and halt what was queued on it.

        Returns what happened, including which jobs were halted, so the
        coordinator sees the consequence rather than discovering it.
        """
        from apps.jobs.models import Job, JobHalt
        from apps.jobs.status_engine import JobStatusEngine
        from apps.production.models import ServiceStation

        if not cls._may_change_state(actor):
            raise PermissionError(
                f"{actor.full_name or actor.email} cannot change machine state."
            )

        if not machine.is_available:
            raise ValueError(f'{machine.name} is already marked down.')

        machine.is_available       = False
        machine.unavailable_reason = reason if reason != 'OTHER' else (note or 'Other')
        machine.unavailable_since  = timezone.now()
        machine.save(update_fields=[
            'is_available', 'unavailable_reason', 'unavailable_since', 'updated_at',
        ])

        halted = cls._halt_jobs_on(machine, actor, note or reason)

        logger.info(
            'MachineService: %s marked down at %s, %s job(s) halted',
            machine.name, machine.branch.code, len(halted),
        )
        return {
            'machine':      machine.name,
            'reason':       machine.unavailable_reason,
            'halted_jobs':  halted,
            'halted_count': len(halted),
        }

    @staticmethod
    def _halt_jobs_on(machine, actor, note) -> list:
        """
        Halt every unfinished job whose route passes through this machine's
        station. Jobs already halted are left alone — a job stopped for a
        missing material does not need a second halt for a broken press.
        """
        from apps.jobs.models import Job
        from apps.jobs.status_engine import JobStatusEngine
        from apps.production.models import ServiceStation

        station = machine.machine_type.station

        candidates = (
            Job.objects
            .filter(
                branch=machine.branch,
                work_state__in=['RECEIVED', 'IN_PRODUCTION', 'FINISHING', 'QUALITY_CHECK'],
            )
            .exclude(status__in=['CANCELLED', 'DRAFT'])
            .prefetch_related('line_items__service', 'halts')
        )

        halted = []
        for job in candidates:
            if any(h.resumed_at is None for h in job.halts.all()):
                continue

            service_ids = [li.service_id for li in job.line_items.all()]
            passes_here = ServiceStation.objects.filter(
                service_id__in=service_ids,
                station=station,
            ).exists()
            if not passes_here:
                continue

            try:
                halt = JobStatusEngine(job).halt(
                    reason='MACHINE_BREAKDOWN',
                    actor=actor,
                    note=note,
                )
                halt.machine = machine
                halt.save(update_fields=['machine', 'updated_at'])
                halted.append(job.job_number)
            except Exception:
                logger.exception(
                    'MachineService: could not halt job %s for machine %s',
                    job.pk, machine.pk,
                )

        return halted

    # ── Bringing it back ─────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def mark_up(cls, machine, actor, resume_jobs=True) -> dict:
        """
        Return a machine to service.

        Resuming its jobs is offered rather than assumed. Some will have
        been moved elsewhere or resumed by hand while the machine was down,
        and blindly resuming everything would undo those decisions.
        """
        from apps.jobs.models import Job, JobHalt
        from apps.jobs.status_engine import JobStatusEngine

        if not cls._may_change_state(actor):
            raise PermissionError(
                f"{actor.full_name or actor.email} cannot change machine state."
            )

        if machine.is_available:
            raise ValueError(f'{machine.name} is already running.')

        was_down_since = machine.unavailable_since

        machine.is_available       = True
        machine.unavailable_reason = ''
        machine.unavailable_since  = None
        machine.save(update_fields=[
            'is_available', 'unavailable_reason', 'unavailable_since', 'updated_at',
        ])

        resumed = []
        if resume_jobs:
            # Only halts this machine caused. The foreign key is what makes
            # that reliable — matching on a note prefix would resume a job
            # the machine never stopped, and would break silently the day
            # the wording changed.
            open_halts = JobHalt.objects.filter(
                machine=machine,
                resumed_at__isnull=True,
            ).select_related('job')

            for halt in open_halts:
                try:
                    JobStatusEngine(halt.job).resume(actor=actor)
                    resumed.append(halt.job.job_number)
                except Exception:
                    logger.exception(
                        'MachineService: could not resume job %s', halt.job_id
                    )

        downtime = None
        if was_down_since:
            downtime = round(
                (timezone.now() - was_down_since).total_seconds() / 60, 1
            )

        logger.info(
            'MachineService: %s back up at %s after %s minutes, %s job(s) resumed',
            machine.name, machine.branch.code, downtime, len(resumed),
        )
        return {
            'machine':         machine.name,
            'downtime_minutes': downtime,
            'resumed_jobs':    resumed,
            'resumed_count':   len(resumed),
        }