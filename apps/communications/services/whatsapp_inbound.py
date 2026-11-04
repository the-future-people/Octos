"""
Inbound WhatsApp: one stored webhook delivery from Meta becomes
Conversations and Messages.

The view stores the raw delivery first, then calls process(event). Each
message is recorded in its own savepoint, so one that cannot be read does
not stop the others, and what went wrong is written onto the event.

Running process() twice on the same event is safe: a message already
recorded is recognised by its wamid and skipped. That makes any failed
event replayable once the cause is fixed.
"""
import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.communications.models import Conversation, Message
from apps.core.phones import lookup_forms, to_international
from apps.customers.models.customer import CustomerProfile

logger = logging.getLogger(__name__)

# WhatsApp's media kinds and the message type each is kept as. A sticker
# is an image as far as anyone reading the inbox is concerned.
MEDIA_TYPES = {
    'image':    Message.IMAGE,
    'sticker':  Message.IMAGE,
    'video':    Message.VIDEO,
    'document': Message.DOCUMENT,
    'audio':    Message.AUDIO,
}


def process(event):
    """
    Read every message and status in one delivery. Returns how many new
    messages were recorded.

    Per-message failures are caught, logged and written to event.error.
    Anything wrong with the delivery as a whole (missing settings, a body
    that is not Meta's shape) raises, and the view records it.
    """
    ours = settings.WHATSAPP_PHONE_NUMBER_ID
    if not ours:
        raise ImproperlyConfigured('WHATSAPP_PHONE_NUMBER_ID is not set.')

    recorded = 0
    failures = []

    for entry in event.payload.get('entry') or []:
        for change in entry.get('changes') or []:
            if change.get('field') != 'messages':
                logger.info('WhatsApp change for field %r ignored', change.get('field'))
                continue

            value = change.get('value') or {}
            number_id = (value.get('metadata') or {}).get('phone_number_id')
            if number_id != ours:
                logger.warning('WhatsApp delivery for another number (%s) ignored', number_id)
                continue

            names = {
                c.get('wa_id'): (c.get('profile') or {}).get('name', '')
                for c in value.get('contacts') or []
            }

            for message in value.get('messages') or []:
                try:
                    with transaction.atomic():
                        if _receive(message, names.get(message.get('from'), '')):
                            recorded += 1
                except Exception as exc:
                    logger.exception(
                        'WhatsApp message %s could not be recorded', message.get('id'),
                    )
                    failures.append(f'{message.get("id")}: {exc!r}')

            for status in value.get('statuses') or []:
                _log_status(status)

    event.processed_at = timezone.now()
    event.error = '\n'.join(failures)
    event.save(update_fields=['processed_at', 'error'])
    return recorded


def _receive(message, profile_name):
    """
    Record one inbound message. True if new, False if already recorded.

    WhatsApp's `from` carries the country code but no '+'. Adding it is
    what lets a number from abroad parse; without it, Ghana as the
    default region would misread it.
    """
    wamid = message.get('id') or ''
    sender = message.get('from') or ''
    phone = to_international('+' + sender) if sender else None
    if not wamid or not phone:
        raise ValueError(f'unusable message {wamid!r} from {sender!r}')

    conversation, _ = Conversation.objects.get_or_create(
        branch=None,
        contact_phone=phone,
        channel=Conversation.WHATSAPP,
    )

    message_type, body, media_id = _content(message)
    try:
        with transaction.atomic():
            # The write is the duplicate check: Meta retries, and the
            # unique wamid lets only the first delivery through.
            Message.objects.create(
                conversation=conversation,
                direction=Message.INBOUND,
                channel=Message.WHATSAPP,
                message_type=message_type,
                body=body,
                media_id=media_id,
                external_id=wamid,
            )
    except IntegrityError:
        logger.info('WhatsApp message %s already recorded', wamid)
        return False

    # After the message, not before: a retry must not reopen a thread
    # that staff resolved after the original arrived.
    _refresh(conversation, phone, profile_name)
    return True


def _refresh(conversation, phone, profile_name):
    """Name, customer and status, brought up to date by a new message."""
    changed = []

    if profile_name and conversation.contact_name != profile_name[:150]:
        conversation.contact_name = profile_name[:150]
        changed.append('contact_name')

    if conversation.customer_id is None:
        customer = CustomerProfile.objects.filter(phone__in=lookup_forms(phone)).first()
        if customer:
            conversation.customer = customer
            changed.append('customer')

    # A customer writing again reopens a resolved thread. Spam stays spam.
    if conversation.status == Conversation.RESOLVED:
        conversation.status = Conversation.OPEN
        changed.append('status')

    if changed:
        conversation.save(update_fields=changed + ['updated_at'])


def _content(message):
    """(message_type, body, media_id) for one WhatsApp message."""
    kind = message.get('type') or ''

    if kind == 'text':
        return Message.TEXT, (message.get('text') or {}).get('body', ''), ''

    if kind in MEDIA_TYPES:
        media = message.get(kind) or {}
        body = media.get('caption') or media.get('filename') or ''
        return MEDIA_TYPES[kind], body, media.get('id', '')

    if kind == 'button':
        return Message.TEXT, (message.get('button') or {}).get('text', ''), ''

    if kind == 'interactive':
        reply = message.get('interactive') or {}
        chosen = reply.get('button_reply') or reply.get('list_reply') or {}
        return Message.TEXT, chosen.get('title', ''), ''

    if kind == 'location':
        place = message.get('location') or {}
        where = ', '.join(p for p in (place.get('name'), place.get('address')) if p)
        coords = f"{place.get('latitude')}, {place.get('longitude')}"
        return Message.TEXT, (f'📍 {where} ({coords})' if where else f'📍 {coords}'), ''

    if kind == 'reaction':
        emoji = (message.get('reaction') or {}).get('emoji', '')
        # An empty emoji is a reaction being taken away.
        return Message.TEXT, (f'Reacted {emoji}' if emoji else 'Removed a reaction'), ''

    if kind == 'contacts':
        shared = []
        for contact in message.get('contacts') or []:
            name = (contact.get('name') or {}).get('formatted_name', '')
            phones = ', '.join(p.get('phone', '') for p in contact.get('phones') or [])
            shared.append(' '.join(part for part in (name, phones) if part))
        return Message.TEXT, 'Shared a contact: ' + '; '.join(shared), ''

    # Never dropped. Staff cannot open WhatsApp on this number to look,
    # so the inbox must at least show that something arrived.
    logger.warning('WhatsApp message type %r not handled (%s)', kind, message.get('id'))
    return Message.TEXT, f'[A {kind or "unknown"} message Octos cannot show yet]', ''


def _log_status(status):
    """
    Delivery and read receipts for messages Octos sent. Logged only until
    outbound messages are recorded (Step 3); then they update them.
    """
    errors = status.get('errors') or []
    level = logging.WARNING if status.get('status') == 'failed' else logging.INFO
    logger.log(
        level, 'WhatsApp status %s for %s%s',
        status.get('status'), status.get('id'), f': {errors}' if errors else '',
    )