"""
Promises, watched.

Every production job carries a promise: worked out by Octos from the
floor when it was paid for, and never set by a person. Lateness is that
promise compared, all the time, with the live estimate of when the job
will really be ready.

    On track   the live estimate lands before the promise
    At risk    it now lands after: there is still time to save it
    Late       the promised time has passed and it is not ready
    Kept       ready by the first promise
    Broken     ready after it

Octos alone moves a promise. When the live estimate slips at least
SLIP past the promise, the promise moves to the new time, the
coordinator and branch manager are told, and so is the customer, with a
brief apology. The first promise is kept forever and the score is
against it, so a revision can never hide a slip. A promise is never
moved earlier: a job that catches up is simply ready sooner.

A delay the customer causes (a returned file, a changed size) restarts
the clock from their fix, without an apology and without counting
against the shop.

The decision itself is `decide`, a pure function, so every rule is
tested exactly; `check` applies it to a job.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

SLIP = timedelta(minutes=15)          # smaller wobbles are not worth an alarm
CUSTOMER_GAP = timedelta(hours=2)     # at most one message this often per job

ON_TRACK, AT_RISK, LATE, KEPT, BROKEN = 'ON_TRACK', 'AT_RISK', 'LATE', 'KEPT', 'BROKEN'


@dataclass
class Decision:
    state: str
    new_promise: object = None        # set only when the promise moves
    tell_staff: bool = False
    tell_customer: bool = False


def round_up_5(at):
    """The next 5-minute mark: 3:41 becomes 3:45, never earlier."""
    extra = (5 - at.minute % 5) % 5
    out = (at + timedelta(minutes=extra)).replace(second=0, microsecond=0)
    return out if out >= at.replace(microsecond=0) else out + timedelta(minutes=5)


def decide(*, promise, live, now, state, last_told):
    """
    What to do about one job, from its promise, the live estimate (None
    where nothing can be said), the time, its current state and when the
    customer was last told.
    """
    state = state or ON_TRACK
    passed = now > promise

    # The live estimate has slipped well past the promise: Octos moves it.
    if live is not None and live >= promise + SLIP:
        new_state = LATE if passed else AT_RISK
        first_late = new_state == LATE and state != LATE
        quiet = last_told is not None and now - last_told < CUSTOMER_GAP
        return Decision(
            state=new_state,
            new_promise=round_up_5(live),
            tell_staff=True,
            tell_customer=first_late or not quiet,
        )

    # Past the promise and not ready, with no better time to give.
    if passed:
        if state == LATE:
            return Decision(state=LATE)
        return Decision(state=LATE, tell_staff=True, tell_customer=True)

    # Back within the promise: quietly on track again. Never announced:
    # earlier is not a promise worth making.
    if state in (AT_RISK, LATE):
        return Decision(state=ON_TRACK)
    return Decision(state=state)


def outcome(*, first_promise, ready_at):
    """Kept or broken, against the first promise and nothing later."""
    if first_promise is None or ready_at is None:
        return None
    return KEPT if ready_at <= first_promise else BROKEN


# ── Applying it to a job ──────────────────────────────────────────────

def _when(at):
    local = timezone.localtime(at)
    today = timezone.localdate()
    day = 'today' if local.date() == today else ('tomorrow' if local.date() == today + timedelta(days=1)
                                               else local.strftime('%A'))
    return f'{local.strftime("%I:%M %p").lstrip("0").lower()} {day}'


def _reason(job):
    from apps.jobs.services.estimates import estimate
    if job.work_state in ('RECEIVED', 'INSPECTING'):
        return 'waiting for inspection'
    est = estimate(job)
    if est and est.held_up:
        return 'a machine is down'
    if est and est.running_over:
        return 'the work is taking longer'
    return 'the queue is longer'


def _staff_for(job):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return list(
        User.objects.filter(branch=job.branch, is_active=True)
        .filter(role__name__in=['BRANCH_MANAGER', 'COORDINATOR', 'FLOW_COORDINATOR'])
    )


def check(job, now=None):
    """Look at one job's promise, and act on what decide() says."""
    from apps.jobs.models import PromiseRevision
    from apps.jobs.services.estimates import job_ready_at
    from apps.notifications.services import notify
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.notify import tell

    now = now or timezone.now()
    promise = job.estimated_ready_at
    if promise is None or job.work_state == 'DONE' or job.handover_state == 'HANDED_OVER':
        return None

    fields = []
    if job.first_promise_at is None:
        job.first_promise_at = promise
        fields.append('first_promise_at')

    d = decide(promise=promise, live=job_ready_at(job, now), now=now,
               state=job.promise_state, last_told=job.promise_told_at)

    if d.new_promise is not None and d.new_promise > promise:
        reason = _reason(job)
        PromiseRevision.objects.create(job=job, from_at=promise, to_at=d.new_promise,
                                       reason=reason, customer_told=d.tell_customer)
        job.estimated_ready_at = d.new_promise
        fields.append('estimated_ready_at')
        order = OnlineOrder.objects.filter(job=job).first()
        if order is not None:
            order.promised_for = d.new_promise
            order.save(update_fields=['promised_for'])
    if d.state != job.promise_state:
        job.promise_state = d.state
        fields.append('promise_state')

    if d.tell_staff:
        word = 'late' if d.state == LATE else 'at risk'
        when = _when(job.estimated_ready_at)
        for person in _staff_for(job):
            notify(person, verb=f'promise_{word.replace(" ", "_")}',
                   message=f'{job.job_number} is {word}: now about {when}.', link=f'/jobs/{job.pk}')

    if d.tell_customer:
        order = OnlineOrder.objects.filter(job=job).first()
        if order is not None and order.lead_id:
            when = _when(job.estimated_ready_at)
            tell(order, 'revised', 'New time',
                 f'Sorry: {job.job_number} is running behind. New time: about {when}.',
                 sms_text=f'Farhat: sorry, {job.job_number} is running behind. New time: about {when}.')
            job.promise_told_at = now
            fields.append('promise_told_at')

    if fields:
        job.save(update_fields=sorted(set(fields)) + ['updated_at'])
    return d


def record_outcome(job, ready_at=None):
    """When the job turns ready: kept or broken, against the first promise."""
    result = outcome(first_promise=job.first_promise_at or job.estimated_ready_at,
                     ready_at=ready_at or timezone.now())
    if result:
        job.promise_state = result
        job.save(update_fields=['promise_state', 'updated_at'])
    return result


def restart_for_customer(job, now=None):
    """
    The customer changed the job (a fixed file, a new size): the clock
    starts again from now. Not the shop's delay, so no apology and no
    mark against the score.
    """
    from apps.jobs.models import PromiseRevision
    from apps.jobs.services.estimates import job_ready_at
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.notify import tell

    now = now or timezone.now()
    fresh = job_ready_at(job, now)
    if fresh is None:
        return None
    fresh = round_up_5(fresh)
    PromiseRevision.objects.create(job=job, from_at=job.estimated_ready_at, to_at=fresh,
                                   reason='the customer changed the job', customer_told=True)
    job.estimated_ready_at = fresh
    job.first_promise_at = fresh
    job.promise_state = ON_TRACK
    job.promise_told_at = now
    job.save(update_fields=['estimated_ready_at', 'first_promise_at', 'promise_state',
                            'promise_told_at', 'updated_at'])
    order = OnlineOrder.objects.filter(job=job).first()
    if order is not None:
        order.promised_for = fresh
        order.save(update_fields=['promised_for'])
        if order.lead_id:
            when = _when(fresh)
            tell(order, 'revised', 'New time',
                 f'Thanks for the change to {job.job_number}. New time: about {when}.',
                 sms_text=f'Farhat: thanks for the change to {job.job_number}. New time: about {when}.')
    return fresh