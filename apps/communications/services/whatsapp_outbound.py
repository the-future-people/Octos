"""
Sending a WhatsApp message to a customer, the one way it is done.

send_text() is called by whoever wants to say something: staff in the
inbox, Octos, a notification. It checks the 24-hour window, records the
message in the conversation as QUEUED, and hands it to the worker after
commit. The worker calls deliver(), which talks to Meta and moves the
message to SENT or FAILED. Delivery and read receipts then arrive
through the webhook.

try_send_text() is the door for system messages (paid, ready, late,
welcome): WhatsApp when the customer's window is open, otherwise None,
so the caller sends the SMS it always sent.

Nothing is ever dropped silently. A refused send raises WindowClosed
before anything is recorded; a failed send stays in the thread as
FAILED, with Meta's reason. A failed system message also goes by SMS,
so the customer still hears.
"""
import logging

from django.db import transaction

from apps.communications.models import Conversation, Message
from apps.communications.services import whatsapp_client
import os

from django.core.files.base import ContentFile

from apps.communications.services.window import window_closes_at, window_open
from apps.core.phones import to_international

logger = logging.getLogger(__name__)

# Meta's code for "outside the 24-hour window". Meta has the final word.
OUTSIDE_WINDOW = '131047'

# System messages that must not fall back to SMS when WhatsApp fails.
# A receipt is long and formatted: as an SMS it would arrive as several
# Unicode parts at several times the cost. Staff print it instead.
NO_SMS_FALLBACK = {'receipt'}


class WindowClosed(Exception):
    """Free text refused: the customer hasn't written in the last 24 hours."""

    def __init__(self, conversation):
        self.closed_at = window_closes_at(conversation)
        when = f'closed at {self.closed_at:%d %b %H:%M}' if self.closed_at else 'never opened'
        super().__init__(
            f'The 24-hour window for {conversation.contact_phone} is {when}. '
            'Only an approved template can be sent until the customer writes again.'
        )


def send_text(conversation, body, sent_by=None, kind='', image=None, filename='card.png', document=None,
              document_mime='application/pdf'):
    """
    Queue free text to the customer. Returns the QUEUED Message.
    sent_by is the staff member, or None when Octos is the sender.
    kind marks a system message (paid, ready…); blank for replies.
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
        message_type=Message.IMAGE if image else (Message.DOCUMENT if document else Message.TEXT),
        status=Message.QUEUED,
        body=body,
        sent_by=sent_by,
        kind=kind,
    )

    if document:
        # A document (a proforma): kept with the message, the body as its caption.
        message.media_file.save(filename, ContentFile(document), save=False)
        Message.objects.filter(pk=message.pk).update(
            media_file=message.media_file.name, media_name=filename,
            media_mime=document_mime, media_size=len(document),
        )

    if image:
        # A card: kept with the message (so the inbox shows it), the body as
        # its caption. Written by update: save() would move the preview again.
        message.media_file.save(filename, ContentFile(image), save=False)
        Message.objects.filter(pk=message.pk).update(
            media_file=message.media_file.name, media_name=filename,
            media_mime='image/png', media_size=len(image), media_pages=1,
        )

    from apps.communications.tasks import deliver_whatsapp
    transaction.on_commit(lambda: deliver_whatsapp.delay(message.pk))
    return message


def try_send_text(phone, body, kind, image=None, filename='card.png'):
    """
    A system message by WhatsApp if this number's window is open.
    Returns the queued Message, or None, meaning "send your SMS".

    Never raises for the ordinary reasons (no conversation, window shut,
    a number that isn't real): those all mean SMS, as before. A
    conversation marked spam never gets WhatsApp from Octos.
    """
    number = to_international(phone or '')
    if not number:
        return None
    conversation = (
        Conversation.objects
        .filter(channel=Conversation.WHATSAPP, branch__isnull=True, contact_phone=number)
        .exclude(status=Conversation.SPAM)
        .first()
    )
    if conversation is None or not window_open(conversation):
        return None
    try:
        return send_text(conversation, body, kind=kind, image=image, filename=filename)
    except (WindowClosed, ValueError):
        return None


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
        phone = message.conversation.contact_phone
        if message.message_type == Message.DOCUMENT and message.media_file:
            with message.media_file.open('rb') as handle:
                content = handle.read()
            wamid = whatsapp_client.send_document(
                phone, content, message.media_name or os.path.basename(message.media_file.name),
                caption=message.body, mime=message.media_mime or 'application/pdf')
        elif message.message_type == Message.IMAGE and message.media_file:
            with message.media_file.open('rb') as handle:
                content = handle.read()
            wamid = whatsapp_client.send_image(phone, content, os.path.basename(message.media_file.name),
                                               caption=message.body)
        else:
            wamid = whatsapp_client.send_text(phone, message.body)
    except whatsapp_client.WhatsAppError as exc:
        if exc.code == OUTSIDE_WINDOW:
            logger.warning('Meta says the window is closed for message %s', message_id)
        else:
            logger.warning('WhatsApp message %s failed: %s', message_id, exc)
        _fail(message, str(exc))
        return
    except Exception as exc:
        # Anything else (settings, a bug) must still end the message as
        # FAILED with a reason, never leave it QUEUED forever.
        logger.exception('WhatsApp message %s could not be sent', message_id)
        _fail(message, f'internal: {exc!r}')
        return

    Message.objects.filter(pk=message_id, status=Message.QUEUED).update(
        status=Message.SENT, external_id=wamid,
    )


def _fail(message, reason):
    """
    FAILED, with the reason. A system message (one with a kind) then goes
    by SMS, so the customer still hears about their order.

    A network failure could, rarely, mean Meta sent it after all. Then
    the customer gets both. Hearing twice beats not hearing.
    """
    failed = Message.objects.filter(pk=message.pk, status=Message.QUEUED).update(
        status=Message.FAILED, error=reason[:500],
    )
    if not failed or not message.kind or message.kind in NO_SMS_FALLBACK:
        return
    try:
        from apps.storefront.services.sms import send_sms
        send_sms(message.conversation.contact_phone, message.body, kind=message.kind)
    except Exception:
        logger.exception('SMS fallback failed for WhatsApp message %s', message.pk)