"""
Front-desk work: jobs the attendants do themselves (14 Nov 2026).

Photocopies, document printing, scanning, lamination, binding, passport
photos and the rest of the instant work don't need the coordinator. He
protects the machines and the production floor; a photocopy ordered online
needs neither. So a job whose every line is instant work goes straight to
the attendants, and a job with anything else on it goes to the coordinator
whole, never split between two people.

The check moves with the job, it isn't skipped. Remote work is verified
before anyone prints (the file opened, the order matched), and for
front-desk work the attendant who took it does that, recorded the same way.

Who does it is decided by "Take it": the first attendant to press it owns
the job, and only she may check, start, hold and finish it (status engine,
_desk_may_move). Nobody takes it within ten minutes of opening hours, and
the BM is told, once.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

ESCALATE_AFTER = timedelta(minutes=10)
# What she confirms before starting: the file is opened and looks right,
# and what was ordered matches what was paid for.
DESK_CHECKS = ('file_opened', 'order_matches')
CLOSED = ('CANCELLED', 'DRAFT')


class DeskRefused(Exception):
    """Not this attendant's to do, or not something that can happen now."""


def is_front_desk_work(job):
    """Every line on the job, add-ons included, is an instant service."""
    from apps.jobs.models import Service

    categories = [line.service.category for line in job.line_items.select_related('service')]
    return bool(categories) and all(c == Service.INSTANT for c in categories)


def route(job):
    """
    Mark the job front desk if its work is. Called once, when the job is
    made, after its lines exist. Returns True when it went to the desk.
    """
    from apps.jobs.models import Job

    if not is_front_desk_work(job):
        return False
    Job.objects.filter(pk=job.pk).update(front_desk=True)
    job.front_desk = True
    _tell_branch(job)
    return True


def landed_at(job, now=None):
    """
    When the front desk could first have seen it: when it was made, or
    this morning's opening for work that arrived overnight.
    """
    from apps.organization.services import hours

    now = timezone.localtime(now or timezone.now())
    opened = hours.opening_at(job.branch, now.date(), now.tzinfo)
    return max(job.created_at, opened)


def queue(branch):
    """Front-desk work not yet done at this branch, soonest promise first."""
    from django.db.models import F
    from apps.jobs.models import Job

    return list(
        Job.objects
        .filter(branch=branch, front_desk=True)
        .exclude(status__in=CLOSED)
        .exclude(work_state='DONE')
        .select_related('customer', 'desk_taken_by')
        .prefetch_related('line_items__service', 'halts', 'verifications')
        .order_by(F('estimated_ready_at').asc(nulls_last=True), 'created_at')
    )


def may_take(user):
    from apps.core.finance_scope import get_role_name
    from apps.jobs.status_engine import ATTENDANT_ROLE, AXIS_OVERRIDE_ROLES

    return get_role_name(user) in ({ATTENDANT_ROLE} | AXIS_OVERRIDE_ROLES)


def take(job_id, branch, user):
    """
    "Take it". The first to press it owns the job; pressing again is
    harmless. Locked, so two attendants tapping at once can't both win.
    """
    from apps.jobs.models import Job

    if not may_take(user):
        raise DeskRefused('Only an attendant can take front-desk work.')
    with transaction.atomic():
        job = Job.objects.select_for_update().filter(pk=job_id, branch=branch).first()
        if job is None or not job.front_desk:
            raise DeskRefused('That is not front-desk work at this branch.')
        if job.status in CLOSED or job.work_state == 'DONE':
            raise DeskRefused(f'{job.job_number} is no longer waiting.')
        if job.desk_taken_by_id == user.pk:
            return job
        if job.desk_taken_by_id:
            holder = job.desk_taken_by
            raise DeskRefused(f'{holder.full_name or holder.email} has already taken {job.job_number}.')
        job.desk_taken_by = user
        job.desk_taken_at = timezone.now()
        job.save(update_fields=['desk_taken_by', 'desk_taken_at', 'updated_at'])
        _tell_branch(job)
        return job


def start(job, actor, signed_checks):
    """
    Both checks signed, then the verification the coordinator would have
    recorded, which also moves the work to in progress. The engine refuses
    anyone but the attendant who took it.
    """
    from apps.jobs.status_engine import JobStatusEngine

    missing = [c for c in DESK_CHECKS if c not in (signed_checks or [])]
    if missing:
        raise DeskRefused('Confirm first: ' + ', '.join(m.replace('_', ' ') for m in missing) + '.')
    with transaction.atomic():
        verification = JobStatusEngine(job).verify(actor=actor, note='Checked at the front desk')
        if hasattr(verification, 'signed_checks'):
            verification.signed_checks = list(DESK_CHECKS)
            verification.save(update_fields=['signed_checks'])
        _tell_branch(job)
    return verification


def finish(job, actor):
    """
    Done. Through the engine like every other job: the history, the
    customer's ready message and PIN, the promise scored, then Pickup.
    """
    from apps.jobs.status_engine import JobStatusEngine

    with transaction.atomic():
        result = JobStatusEngine(job).move_work('DONE', actor, notes='Done at the front desk')
        _tell_branch(job)
    return result


def hold(job, actor, outcome, note=''):
    """
    "Problem with this job": what she found, and the job held while the
    customer is asked. Both or neither, as the coordinator's suspend.
    """
    from apps.jobs.status_engine import JobStatusEngine

    with transaction.atomic():
        engine = JobStatusEngine(job)
        engine.reject_verification(outcome=outcome, actor=actor, note=note)
        engine.halt(reason='AWAITING_CUSTOMER', actor=actor, note=note)
        _tell_branch(job)


def resume(job, actor):
    """The customer answered: back to where it was."""
    from apps.jobs.status_engine import JobStatusEngine

    with transaction.atomic():
        JobStatusEngine(job).resume(actor)
        _tell_branch(job)


def escalate(now=None):
    """
    Front-desk work nobody has taken ten minutes into opening hours: the
    BM is told, once per job. The louder re-alert at five minutes is the
    attendant's screen; this is the step after it. Returns how many.
    """
    from apps.accounts.models import CustomUser
    from apps.jobs.models import Job
    from apps.notifications.services import notify_many
    from apps.organization.services import hours

    now = now or timezone.now()
    waiting = (
        Job.objects
        .filter(front_desk=True, desk_taken_by__isnull=True, desk_escalated_at__isnull=True)
        .exclude(status__in=CLOSED)
        .exclude(work_state='DONE')
        .select_related('branch')
    )
    told = 0
    for job in waiting:
        try:
            if not hours.is_open(job.branch, now) or now - landed_at(job, now) < ESCALATE_AFTER:
                continue
            if not Job.objects.filter(pk=job.pk, desk_escalated_at__isnull=True).update(desk_escalated_at=now):
                continue
            managers = CustomUser.objects.filter(branch=job.branch, role__name='BRANCH_MANAGER', is_active=True)
            promised = ''
            if job.estimated_ready_at:
                at = timezone.localtime(job.estimated_ready_at)
                promised = f' It was promised for {at.strftime("%I:%M %p").lstrip("0").lower()}.'
            notify_many(
                managers, verb='front_desk_unclaimed',
                message=(f'{job.job_number} ({job.title}) has waited 10 minutes at the front desk '
                         f'and no attendant has taken it.{promised}'),
            )
            told += 1
        except Exception:
            logger.exception('Could not escalate front-desk job %s', job.pk)
    return told


def _tell_branch(job):
    """Every screen at the branch refreshes its Work list once this commits."""
    from apps.core.broadcast import broadcast_invalidation

    branch_id = job.branch_id
    transaction.on_commit(lambda: broadcast_invalidation(branch_id, ['deskQueue', 'jobs', 'job-detail']))
