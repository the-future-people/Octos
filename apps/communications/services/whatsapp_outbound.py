"""
Sending a WhatsApp message to a customer, the one way it is done.

send_text() is called by whoever wants to say something: staff in the
inbox, Octos, a notification. It checks the 24-hour window, records the
message in the conversation as QUEUED, and hands it to the worker after
commit. The worker calls deliver(), which talks to Meta and moves the
message to SENT or FAILED. Delivery and read receipts then arrive
through the webhook.

Nothing is ever dropped silently. A refused send raises WindowClosed
before anything is recorded; a failed send stays in the thread as
FAILED, with Meta's reason, for staff to see.
"""
import logging

from django.db import transaction

from apps.communications.models import Conversation, Message
from apps.communications.services import whatsapp_client
from apps.communications.services.window import window_closes_at, window_open

logger = logging.getLogger(__name__)

# Meta's code for "outside the 24-hour window". Meta has the final word.
OUTSIDE_WINDOW = '131047'


class WindowClosed(Exception):
    """Free text refused: the customer hasn't written in the last 24 hours."""

    def __init__(self, conversation):
        self.closed_at = window_closes_at(conversation)
        when = f'closed at {self.closed_at:%d %b %H:%M}' if self.closed_at else 'never opened'
        super().__init__(
            f'The 24-hour window for {conversation.contact_phone} is {when}. '
            'Only an approved template can be sent until the customer writes again.'
        )


def send_text(conversation, body, sent_by=None):
    """
    Queue free text to the customer. Returns the QUEUED Message.
    sent_by is the staff member, or None when Octos is the sender.
    Raises WindowClosed when the window is shut.
    """
    if conversation.channel != Conversation.WHATSAPP:
        raise ValueError(f'conversation {conversation.pk} is not a WhatsApp conversation')
    body = (body or '').strip()
    if not body:
        raise ValueError('nothing to send')
    if not window_open(conversation):
        raise WindowClosed(conversation)

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.OUTBOUND,
        channel=Message.WHATSAPP,
        message_type=Message.TEXT,
        status=Message.QUEUED,
        body=body,
        sent_by=sent_by,
    )

    from apps.communications.tasks import deliver_whatsapp
    transaction.on_commit(lambda: deliver_whatsapp.delay(message.pk))
    return message


def deliver(message_id):
    """
    Send one QUEUED message to Meta. Runs in the worker.

    Safe to run twice: anything no longer QUEUED is left alone, so a
    retried task can never send the same message again.

    Updates use .update(), not save(): save() would rewrite the
    conversation's preview and last-message time for a status change.
    """
    message = (
        Message.objects.select_related('conversation')
        .filter(pk=message_id, status=Message.QUEUED)
        .first()
    )
    if message is None:
        logger.info('WhatsApp message %s is not queued; nothing to send', message_id)
        return

    try:
        wamid = whatsapp_client.send_text(message.conversation.contact_phone, message.body)
    except whatsapp_client.WhatsAppError as exc:
        if exc.code == OUTSIDE_WINDOW:
            logger.warning('Meta says the window is closed for message %s', message_id)
        else:
            logger.warning('WhatsApp message %s failed: %s', message_id, exc)
        _fail(message_id, str(exc))
        return
    except Exception as exc:
        # Anything else (settings, a bug) must still end the message as
        # FAILED with a reason, never leave it QUEUED forever.
        logger.exception('WhatsApp message %s could not be sent', message_id)
        _fail(message_id, f'internal: {exc!r}')
        return

    Message.objects.filter(pk=message_id, status=Message.QUEUED).update(
        status=Message.SENT, external_id=wamid,
    )


def _fail(message_id, reason):
    Message.objects.filter(pk=message_id, status=Message.QUEUED).update(
        status=Message.FAILED, error=reason[:500],
    )