"""
Jobs on the spine (Layer 1, Step 1.1d, 11 Nov 2026).

JobStatusEngine guards every job transition and writes JobStatusLog. Here
each of those moves is described for the spine: one event per move, named
for what it means to a customer or a shop (ready, collected, paid), keyed by
its JobStatusLog row so it is recorded once.

Job creation is the one thing heard through a signal, because jobs are
created in several places (online conversion, counter intake, late jobs,
drafts) with no single door. A signal catches them all; it is also invisible
to anyone reading those places, which is why this note exists.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.spine import kinds
from apps.spine.models import Event
from apps.spine.recorder import record

# (axis, to_state) -> the meaningful event name. Anything else is job.status_changed.
MILESTONES = {
    ('WORK', 'DONE'):               kinds.JOB_READY,
    ('HANDOVER', 'HANDED_OVER'):    kinds.JOB_COLLECTED,
    ('PAYMENT', 'SETTLED'):         kinds.JOB_PAID,
    ('PAYMENT', 'DEPOSIT_PAID'):    kinds.JOB_DEPOSIT_PAID,
    ('RECORD', 'CANCELLED'):        kinds.JOB_CANCELLED,
}


def kind_for_move(axis, to_state):
    """The event name for a move on an axis (RECORD = the legacy status)."""
    return MILESTONES.get((str(axis).upper(), to_state), kinds.JOB_STATUS_CHANGED)


def _actor_type(actor):
    return Event.STAFF if actor is not None else Event.SYSTEM


def record_job_move(job, axis, from_state, to_state, actor, notes, log):
    """Called by JobStatusEngine right after it writes the JobStatusLog row."""
    return record(
        kind_for_move(axis, to_state),
        actor=_actor_type(actor), actor_user=actor,
        job=job, customer=getattr(job, 'customer', None), branch=getattr(job, 'branch', None),
        key=f'jobstatus:{log.pk}',
        payload={'job_number': job.job_number, 'axis': str(axis), 'from': from_state,
                 'to': to_state, 'status_log_id': log.pk},
        reason=notes or '',
    )


def record_halt(job, halt, actor):
    return record(
        kinds.JOB_HALTED, actor=_actor_type(actor), actor_user=actor,
        job=job, customer=getattr(job, 'customer', None), branch=getattr(job, 'branch', None),
        key=f'jobhalt:{halt.pk}',
        payload={'job_number': job.job_number, 'halt_reason': halt.reason,
                 'work_state': halt.work_state_at_halt},
        reason=f'{halt.reason}' + (f': {halt.note}' if getattr(halt, 'note', '') else ''),
    )


def record_resume(job, halt, actor):
    return record(
        kinds.JOB_RESUMED, actor=_actor_type(actor), actor_user=actor,
        job=job, customer=getattr(job, 'customer', None), branch=getattr(job, 'branch', None),
        key=f'jobresume:{halt.pk}',
        payload={'job_number': job.job_number, 'halt_reason': halt.reason},
    )


def record_job_created(job):
    """Every new Job, wherever it was made. Staff when someone took it in, else the system."""
    taker = getattr(job, 'intake_by', None)
    return record(
        kinds.JOB_CREATED, actor=_actor_type(taker), actor_user=taker,
        job=job, customer=getattr(job, 'customer', None), branch=getattr(job, 'branch', None),
        key=f'job:{job.pk}:created',
        payload={'job_number': job.job_number, 'job_type': job.job_type,
                 'status': job.status, 'intake_channel': getattr(job, 'intake_channel', '')},
    )


@receiver(post_save, sender='jobs.Job', dispatch_uid='spine_job_created')
def _job_saved(sender, instance, created, raw=False, **kwargs):
    # raw: loading fixtures, not a real creation
    if created and not raw:
        record_job_created(instance)
