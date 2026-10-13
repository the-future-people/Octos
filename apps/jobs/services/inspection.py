"""
Who is inspecting what, and which job comes next.

The arrivals queue is strict: a coordinator takes the job at the top and
nothing else. Choosing lets the awkward file wait while easier ones go
through, and the job left behind is the one that goes late. So the order
is decided here, once, and both the queue the coordinator sees and the
claim that opens a job read it from the same place.

A claim is not a state. It says who has the job open in the inspection
workspace, so two coordinators never check the same file. It lapses
after ten minutes without a refresh, because a tablet left on a bench
must not hold the queue; the workspace refreshes it while open.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.jobs.models import Job

CLAIM_TTL = timedelta(minutes=10)


class ClaimRefused(Exception):
    """The job is not this coordinator's to take."""


def current_promise(job):
    """
    When this job is due: the time Octos promised, from the floor and its
    capacity. Never a time the customer asked for; that is a wish the
    branch may or may not honour.

    One function, so that when promises can be revised the board, the
    flags and the queue change here and nowhere else.
    """
    return job.estimated_ready_at


def claim_is_live(job, now=None):
    now = now or timezone.now()
    return bool(
        job.inspecting_by_id
        and job.inspecting_since
        and now - job.inspecting_since < CLAIM_TTL
    )


def arrival_queue(branch):
    """
    Paid remote work nobody has cleared, soonest promise first.

    Ties go to whoever arrived first. A job with no promise sorts last:
    nothing says it is urgent, and a promised job must not wait behind it.
    Held jobs are left out; they have been looked at and are waiting on
    someone else.
    """
    candidates = (
        Job.objects
        .filter(
            branch=branch,
            intake_channel__in=Job.REMOTE_CHANNELS,
            work_state='RECEIVED',
        )
        .exclude(status__in=['CANCELLED', 'DRAFT'])
        .exclude(payment_state='UNPAID')
        .select_related('customer', 'intake_by', 'inspecting_by')
        .prefetch_related('line_items__service', 'verifications', 'halts')
        # Mirrors current_promise(). When revisions exist, this changes
        # with it.
        .order_by(F('estimated_ready_at').asc(nulls_last=True), 'created_at')
    )
    return [
        job for job in candidates
        if not job.is_verified
        and not any(h.resumed_at is None for h in job.halts.all())
    ]


def next_up(queue, user, now=None):
    """
    The one job this coordinator may open.

    Their own live claim first, since they are already in the middle of
    it. Otherwise the first job nobody else holds.
    """
    now = now or timezone.now()
    for job in queue:
        if claim_is_live(job, now) and job.inspecting_by_id == user.pk:
            return job
    for job in queue:
        if not claim_is_live(job, now):
            return job
    return None


def claim(job_id, branch, user):
    """
    Take a job into the inspection workspace, or refresh a claim already
    held. Refused unless it is this coordinator's next job, which is the
    strict queue enforced on the server rather than by hidden buttons.
    """
    now = timezone.now()
    with transaction.atomic():
        job = (
            Job.objects
            .select_for_update()
            .filter(pk=job_id, branch=branch)
            .first()
        )
        if job is None:
            raise ClaimRefused('That job is not at this branch.')

        if claim_is_live(job, now) and job.inspecting_by_id != user.pk:
            holder = job.inspecting_by
            name = holder.full_name or holder.email
            raise ClaimRefused(f'{name} is already inspecting {job.job_number}.')

        mine = next_up(arrival_queue(branch), user, now)
        if mine is None or mine.pk != job.pk:
            raise ClaimRefused(
                f'{job.job_number} is not next. '
                f'Take the job at the top of the queue.'
            )

        job.inspecting_by = user
        job.inspecting_since = now
        job.save(update_fields=['inspecting_by', 'inspecting_since', 'updated_at'])
        return job


def release(job, user):
    """
    Let go of a job: on clearing, on suspending, or on closing the
    workspace. Only the holder's own claim, so a late release from one
    tablet cannot free a job someone else has since taken.
    """
    Job.objects.filter(pk=job.pk, inspecting_by=user).update(
        inspecting_by=None, inspecting_since=None,
    )