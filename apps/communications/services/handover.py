"""
Who answers a conversation: Octos, or a person.

Octos answers by default. A person takes over with the button, or by
replying, since Octos must never talk over someone who is typing. They
hand back with the button. Octos hands over itself when a person is
needed, and says why.

Nobody is left waiting because someone took over and walked away: once a
person has the conversation and the customer's message is the last one,
the person handling it is reminded after 30 minutes. If the reminder is
ignored for 10 more minutes, Octos takes the conversation back. Any reply
from staff clears the clock.

Every switch leaves an internal note in the thread, so anyone opening it
can see who had it and why, and an event on the spine (10 Nov 2026), so
Octos itself knows what happened. The switch, its note and its event are
written in one transaction: all three are saved, or none.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.communications.models import Conversation, Message
from apps.spine import kinds
from apps.spine.models import Event
from apps.spine.recorder import record

logger = logging.getLogger(__name__)

REMIND_AFTER = timedelta(minutes=30)
TAKE_BACK_AFTER = timedelta(minutes=10)


def take_over(conversation, user):
    """A person answers from now on; Octos goes quiet in this thread."""
    with transaction.atomic():
        _switch(conversation, Conversation.STAFF, reason='')
        if not conversation.assigned_to_id:
            conversation.assigned_to = user
            conversation.save(update_fields=['assigned_to'])
        _note(conversation, f'{user.full_name} took over from Octos.', user)
        record(kinds.STAFF_TOOK_OVER, actor=Event.STAFF, actor_user=user,
               conversation=conversation, customer=conversation.customer,
               reason=f'{user.full_name} took over from Octos.')


def hand_back(conversation, user=None, why=''):
    """
    Octos answers from now on, handed back by a person or taking back after silence.

    Who hands back matters (11 Nov 2026). A person handing back means "I've
    dealt with everything up to now", sometimes by a phone call Octos never
    sees, so Octos waits for the customer's next message. Octos taking back
    after an ignored reminder means nobody answered, so Octos answers now.
    """
    with transaction.atomic():
        _switch(conversation, Conversation.OCTOS, reason='')
        who = user.full_name if user else 'Octos'
        _note(conversation, f'{who} handed the conversation back to Octos.' if user else f'Octos took the conversation back: {why}', user)
        if user:
            record(kinds.STAFF_HANDED_BACK, actor=Event.STAFF, actor_user=user,
                   conversation=conversation, customer=conversation.customer,
                   reason=f'{user.full_name} handed the conversation back to Octos.')
        else:
            record(kinds.OCTOS_TOOK_BACK, actor=Event.OCTOS,
                   conversation=conversation, customer=conversation.customer,
                   reason=f'Octos took the conversation back: {why}')
        # Only when Octos took back: a customer nobody answered gets an answer
        # now. After a person's hand-back, what was waiting is theirs, handled.
        waiting = conversation.messages.filter(is_internal_note=False).order_by('-created_at').first()
        if user is None and waiting is not None and waiting.direction == Message.INBOUND:
            from apps.communications.services.whatsapp_inbound import wake_octos
            wake_octos(conversation, waiting)


def octos_hands_over(conversation, reason):
    """Octos needs a person: hand over, say why, and alert whoever should come."""
    with transaction.atomic():
        _switch(conversation, Conversation.STAFF, reason=_clip(reason, 200))
        _note(conversation, f'Octos asked for a person: {reason}', None)
        record(kinds.OCTOS_ASKED_FOR_PERSON, actor=Event.OCTOS,
               conversation=conversation, customer=conversation.customer,
               reason=f'Octos asked for a person: {reason}')
    # Outside the transaction: an alert is a side effect, and one that fails
    # must not undo the hand-over itself.
    _alert(conversation, verb='needs_you', message=f'Needs you: {reason}')


def staff_replied(conversation, user):
    """A staff reply: it takes the conversation over, and clears any reminder."""
    # Octos answering, or Octos still answering while waiting for a person:
    # either way a staff reply means a person has it now.
    if conversation.handled_by == Conversation.OCTOS or conversation.handoff_reason:
        take_over(conversation, user)
    elif conversation.reminded_at:
        conversation.reminded_at = None
        conversation.save(update_fields=['reminded_at'])


def waiting_since(conversation):
    """When the customer's unanswered message arrived, or None if nobody is waiting."""
    last = (
        conversation.messages.filter(is_internal_note=False)
        .order_by('-created_at').first()
    )
    if last is not None and last.direction == Message.INBOUND:
        return last.created_at
    return None


def watch(now=None):
    """
    Run every minute. For each conversation a person has: remind after 30
    minutes of a customer waiting, take back 10 minutes after an ignored
    reminder. Returns (reminded, taken_back) counts for the log.
    """
    now = now or timezone.now()
    reminded = taken_back = 0
    held = (
        Conversation.objects
        .filter(handled_by=Conversation.STAFF)
        .exclude(status__in=[Conversation.RESOLVED, Conversation.SPAM])
    )
    for conversation in held:
        since = waiting_since(conversation)
        if since is None:
            continue
        if conversation.reminded_at is None:
            if now - since >= REMIND_AFTER:
                minutes = int((now - since).total_seconds() // 60)
                _alert(conversation, verb='customer_waiting',
                       message=f'{conversation.display_name} has waited {minutes} minutes for a reply.')
                with transaction.atomic():
                    conversation.reminded_at = now
                    conversation.save(update_fields=['reminded_at'])
                    record(kinds.STAFF_REMINDED, actor=Event.SYSTEM,
                           conversation=conversation, customer=conversation.customer,
                           payload={'waited_minutes': minutes},
                           reason=f'The customer had waited {minutes} minutes for a person.')
                reminded += 1
        elif now - conversation.reminded_at >= TAKE_BACK_AFTER:
            hand_back(conversation, why='no reply 10 minutes after the reminder.')
            taken_back += 1
    return reminded, taken_back


def _switch(conversation, handler, reason):
    conversation.handled_by = handler
    conversation.handled_since = timezone.now()
    conversation.handoff_reason = reason
    conversation.reminded_at = None
    conversation.save(update_fields=['handled_by', 'handled_since', 'handoff_reason', 'reminded_at'])


def _note(conversation, text, user):
    Message.objects.create(
        conversation=conversation,
        direction=Message.OUTBOUND,
        channel=Message.SYSTEM,
        message_type=Message.NOTE,
        is_internal_note=True,
        body=text,
        sent_by=user,
    )


def _alert(conversation, verb, message):
    """The assigned person, or the managers who'd be told of a new message there."""
    try:
        from apps.notifications.services import notify_many
        from apps.notifications.signals import _conversation_assignees
        notify_many(
            recipients=_conversation_assignees(conversation),
            verb=verb,
            message=message,
            link='/portal/inbox/',
        )
    except Exception:
        # An alert that fails must not stop the switch itself; it is logged
        # in full so it can't fail quietly.
        logger.exception('Could not alert about conversation %s', conversation.pk)



def resolved(conversation, user=None):
    """A resolved conversation is handled: no longer 'needs you', and Octos answers what comes next."""
    with transaction.atomic():
        conversation.handled_by = Conversation.OCTOS
        conversation.handoff_reason = ''
        conversation.reminded_at = None
        conversation.save(update_fields=['handled_by', 'handoff_reason', 'reminded_at'])
        record(kinds.CONVERSATION_RESOLVED, actor=Event.STAFF if user else Event.SYSTEM,
               actor_user=user, conversation=conversation, customer=conversation.customer,
               reason='Marked resolved.')


def _clip(text, limit):
    """Cut at a word, never mid-word, with an ellipsis when anything was cut."""
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rsplit(' ', 1)[0].rstrip(',;:') + '…'
