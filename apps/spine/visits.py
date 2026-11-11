"""
Visits: one customer, one sitting (Layer 1, Steps 1.2 and 1.3, 11 Nov 2026).

A Visit is a projection: not a fact of its own, but a summary built from the
events on the spine. record() calls attach() for every new event, so nothing
else in Octos has to know visits exist.

The rules, in the order they apply:

  1. Only an opening event (a customer's message, a counter presence or claim)
     can open a visit. A delivery receipt never does.
  2. A visit quiet for more than QUIET_GAP is closed before anything new joins
     it, backdated to when it went quiet. The customer's next message is a new
     visit, and in a print shop it is usually a new job.
  3. An outcome event (job created, paid, collected, resolved) closes the visit
     with that outcome, and points at the event that proved it.
  4. close_quiet() sweeps visits nobody wrote to again: NO_ACTION, or ABANDONED
     when a quote or payment link was left hanging. Timed-out closes are kept
     apart from real outcomes in every report.
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.spine import kinds

QUIET_GAP = timedelta(hours=2)

OPENING = {kinds.MESSAGE_RECEIVED, kinds.PRESENCE_COUNTER, kinds.COUNTER_CLAIMED}

# Paperwork, not activity: these join an open visit but never keep it alive.
NOT_ACTIVITY = {
    kinds.MESSAGE_DELIVERED, kinds.MESSAGE_READ, kinds.OCTOS_STAYED_SILENT,
    kinds.OCTOS_SHADOWED, kinds.STAFF_REMINDED,
}

# Real outcomes, each backed by the event that proves it.
OUTCOMES = {
    'job.created': 'JOB_CREATED',
    'job.paid': 'PAID',
    'payment.succeeded': 'PAID',
    'job.collected': 'COLLECTED',
    'conversation.resolved': 'RESOLVED',
}

# Left hanging: a visit that timed out after one of these was abandoned, not idle.
HANGING = {kinds.QUOTE_GIVEN, kinds.PAYMENT_LINK_SENT}


def attach(event):
    """Give a new event its visit, opening or closing visits as the rules say."""
    from apps.spine.models import Event, Visit

    visit = _open_visit_for(event)
    if visit is None:
        return None

    Event.objects.filter(pk=event.pk).update(visit=visit)
    event.visit = visit

    changed = []
    if event.kind not in NOT_ACTIVITY and event.occurred_at > visit.last_activity_at:
        visit.last_activity_at = event.occurred_at
        changed.append('last_activity_at')
    if event.kind in (kinds.STAFF_TOOK_OVER, kinds.COUNTER_CLAIMED) and event.actor_user_id:
        visit.attended_by_id = event.actor_user_id
        changed.append('attended_by')
    if event.kind in (kinds.COUNTER_CLAIMED, kinds.PRESENCE_COUNTER) and visit.presence != Visit.AT_COUNTER:
        visit.presence = Visit.AT_COUNTER
        changed.append('presence')
    if event.customer_id and not visit.customer_id:
        visit.customer_id = event.customer_id
        changed.append('customer')
    if changed:
        visit.save(update_fields=changed)

    outcome = OUTCOMES.get(event.kind)
    if outcome:
        close(visit, outcome, at=event.occurred_at, by_event=event)
    return visit


def _open_visit_for(event):
    """The visit this event belongs to: the open one, a fresh one, or none."""
    from apps.spine.models import Visit

    if event.conversation_id:
        scope = {'conversation_id': event.conversation_id}
    elif event.customer_id:
        scope = {'customer_id': event.customer_id}
    else:
        return None

    visit = (Visit.objects.select_for_update()
             .filter(closed_at__isnull=True, **scope).order_by('-opened_at').first())

    # Rule 2: quiet too long. Close it as it stood, then treat this as new.
    if visit is not None and event.occurred_at - visit.last_activity_at > QUIET_GAP:
        _time_out(visit)
        visit = None

    if visit is not None:
        return visit
    if event.kind not in OPENING or not event.conversation_id:
        return None

    try:
        with transaction.atomic():
            return Visit.objects.create(
                conversation_id=event.conversation_id, customer_id=event.customer_id,
                branch_id=event.branch_id,
                opened_at=event.occurred_at, last_activity_at=event.occurred_at,
            )
    except IntegrityError:
        # Another worker opened it a moment ago; the database let only one win.
        return Visit.objects.get(conversation_id=event.conversation_id, closed_at__isnull=True)


def close(visit, outcome, at, by_event=None, timed_out=False, reason=''):
    """Close a visit with its outcome, and say so on the spine."""
    from apps.spine.recorder import record

    visit.outcome = outcome
    visit.closed_at = at
    visit.timed_out = timed_out
    visit.closed_by_event = by_event
    visit.save(update_fields=['outcome', 'closed_at', 'timed_out', 'closed_by_event'])
    record(kinds.VISIT_CLOSED, conversation=visit.conversation, customer=visit.customer,
           branch=visit.branch, occurred_at=at, key=f'visit-closed:{visit.pk}',
           payload={'visit_id': visit.pk, 'outcome': outcome, 'timed_out': timed_out},
           reason=reason or f'Closed: {outcome.replace("_", " ").lower()}.',
           _visit=visit)

    # A counter visit ends with the visit: the quiet window (counter_until) is
    # cleared, so a question typed afterwards is answered. The customer who
    # types after the work is done has most likely left the counter.
    conversation = visit.conversation
    if conversation is not None and getattr(conversation, 'counter_until', None):
        type(conversation).objects.filter(pk=conversation.pk).update(counter_until=None)
        conversation.counter_until = None


def _time_out(visit):
    """Quiet for QUIET_GAP: closed when it went quiet, as idle or abandoned."""
    hanging = visit.events.filter(kind__in=HANGING).exists()
    outcome = 'ABANDONED' if hanging else 'NO_ACTION'
    close(visit, outcome, at=visit.last_activity_at + QUIET_GAP, timed_out=True,
          reason='Quiet for 2 hours' + (' after a quote or payment link.' if hanging else '.'))


def close_quiet(now=None):
    """The sweep: every open visit quiet for longer than QUIET_GAP. Returns how many."""
    from apps.spine.models import Visit

    now = now or timezone.now()
    closed = 0
    for pk in Visit.objects.filter(closed_at__isnull=True,
                                   last_activity_at__lt=now - QUIET_GAP).values_list('pk', flat=True):
        with transaction.atomic():
            visit = Visit.objects.select_for_update().filter(pk=pk, closed_at__isnull=True).first()
            if visit is not None:
                _time_out(visit)
                closed += 1
    return closed
