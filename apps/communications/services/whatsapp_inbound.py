import re
"""
Inbound WhatsApp: one stored webhook delivery from Meta becomes
Conversations and Messages.

The view stores the raw delivery first, then calls process(event). Each
message is recorded in its own savepoint, so one that cannot be read does
not stop the others, and what went wrong is written onto the event.

Running process() twice on the same event is safe: a message already
recorded is recognised by its wamid and skipped. That makes any failed
event replayable once the cause is fixed.

Every new message and every delivery receipt is also written to the spine
(10 Nov 2026), inside the same transaction as the message itself, keyed by
WhatsApp's own id so a retried delivery is recorded once.
"""
import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.communications.models import Conversation, Message
from apps.core.phones import lookup_forms, to_international
from apps.customers.models.customer import CustomerProfile
from apps.spine import kinds
from apps.spine.models import Event
from apps.spine.recorder import record

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

            # Who wrote: by phone (wa_id) or, for a customer with a WhatsApp
            # username, by Meta's user id (9 Nov 2026).
            people = {}
            for c in value.get('contacts') or []:
                profile = c.get('profile') or {}
                who = {'name': profile.get('name', ''), 'username': profile.get('username', ''),
                       'user_id': c.get('user_id') or ''}
                for key in (c.get('wa_id'), c.get('user_id')):
                    if key:
                        people[key] = who
            names = {key: who['name'] for key, who in people.items()}

            for message in value.get('messages') or []:
                try:
                    with transaction.atomic():
                        who = people.get(message.get('from')) or people.get(message.get('from_user_id')) or {}
                        if _receive(message, who.get('name', ''), who):
                            recorded += 1
                except Exception as exc:
                    logger.exception(
                        'WhatsApp message %s could not be recorded', message.get('id'),
                    )
                    failures.append(f'{message.get("id")}: {exc!r}')

            for status in value.get('statuses') or []:
                _apply_status(status)

    event.processed_at = timezone.now()
    event.error = '\n'.join(failures)
    if failures:
        _tell_managers(event)
    event.save(update_fields=['processed_at', 'error'])
    return recorded


def _receive(message, profile_name, who=None):
    """
    Record one inbound message. True if new, False if already recorded.

    WhatsApp's `from` carries the country code but no '+'. Adding it is
    what lets a number from abroad parse; without it, Ghana as the
    default region would misread it.
    """
    who = who or {}
    wamid = message.get('id') or ''
    sender = message.get('from') or ''
    user_id = message.get('from_user_id') or message.get('user_id') or who.get('user_id') or ''
    if USER_ID.match(sender):          # a username user's 'from' is their user id
        user_id, sender = user_id or sender, ''
    phone = to_international('+' + sender) if sender else None
    if not wamid or not (phone or user_id):
        raise ValueError(f'unusable message {wamid!r} from {sender!r}')

    conversation = _conversation_for(phone, user_id, who.get('username', ''))

    message_type, body, media_id = _content(message)
    media_name, media_mime = _media_details(message)
    try:
        with transaction.atomic():
            # The write is the duplicate check: Meta retries, and the
            # unique wamid lets only the first delivery through.
            message = Message.objects.create(
                conversation=conversation,
                direction=Message.INBOUND,
                channel=Message.WHATSAPP,
                message_type=message_type,
                body=body,
                media_id=media_id,
                media_name=media_name,
                media_mime=media_mime,
                external_id=wamid,
                reply_to=_quoted(conversation, message.get('context')),
            )
    except IntegrityError:
        logger.info('WhatsApp message %s already recorded', wamid)
        return False

    # After the message, not before: a retry must not reopen a thread
    # that staff resolved after the original arrived.
    _refresh(conversation, phone, profile_name)
    _opt_out_if_asked(conversation, body)

    # The spine: what arrived, from whom, keyed by WhatsApp's id. The words
    # stay on the Message; the event carries only what describes it.
    record(kinds.MESSAGE_RECEIVED, actor=Event.CUSTOMER,
           conversation=conversation, customer=conversation.customer,
           key=f'wa:{wamid}',
           payload={'message_id': message.pk, 'type': message_type,
                    'has_file': bool(media_id), 'mime': media_mime,
                    'quoted': message.reply_to_id})

    wake_octos(conversation, message, pause=8)
    if message.media_id:
        _keep_media(message)
    return True


def wake_octos(conversation, message, pause=0):
    """
    Ask Octos to consider a customer's message once it is committed.

    A fresh message (pause given) waits for the customer to go quiet
    (assistant/counter.py): briefly after words, longer after a file or a
    message with no words. Each new message starts its own wait and only
    the latest one's run answers, so a burst, or a stream of photos, gets
    one reply after the last. No typing dots here: they show only once
    Octos really starts writing. A hand-back (pause 0) answers at once.
    Off: nothing is queued.
    """
    from django.conf import settings
    if settings.OCTOS_ASSISTANT_MODE not in ('shadow', 'live'):
        return
    from apps.communications.assistant import counter
    from apps.communications.tasks import answer_whatsapp
    if pause:
        pause = counter.quiet_window(message)
    transaction.on_commit(
        lambda: answer_whatsapp.apply_async((conversation.pk, message.pk), countdown=pause)
    )


def _refresh(conversation, phone, profile_name):
    """Name, customer and status, brought up to date by a new message."""
    changed = []

    if profile_name and conversation.contact_name != profile_name[:150]:
        conversation.contact_name = profile_name[:150]
        changed.append('contact_name')

    if conversation.customer_id is None:
        customer = CustomerProfile.objects.filter(phone__in=lookup_forms(phone)).first() if phone else None
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


# Meta's status words, and how far along each one is. Statuses can arrive
# out of order (a "delivered" after a "read"), so a message only ever
# moves forward. Failed is the exception: it can land at any point.
STATUS_MAP = {
    'sent':      Message.SENT,
    'delivered': Message.DELIVERED,
    'read':      Message.READ,
    'failed':    Message.FAILED,
}
PROGRESS = [Message.QUEUED, Message.SENT, Message.DELIVERED, Message.READ]

# Receipts worth an event on the spine. "sent" only means Meta accepted it,
# which the outbound side records itself.
STATUS_EVENTS = {
    'delivered': kinds.MESSAGE_DELIVERED,
    'read':      kinds.MESSAGE_READ,
    'failed':    kinds.MESSAGE_FAILED,
}


def _apply_status(status):
    """
    A delivery receipt for a message Octos sent. Updates that message,
    forward only. A receipt that matches nothing (a message sent before
    Octos recorded sends, or one racing ahead of its own wamid) is logged
    and ignored.
    """
    wamid = status.get('id') or ''
    word = status.get('status') or ''
    new = STATUS_MAP.get(word)
    if not wamid or new is None:
        logger.info('WhatsApp status %r for %r ignored', word, wamid)
        return

    ours = Message.objects.filter(
        channel=Message.WHATSAPP, direction=Message.OUTBOUND, external_id=wamid,
    )
    sent = ours.select_related('conversation').first()

    reason = ''
    if new == Message.FAILED:
        reason = '; '.join(
            f"{e.get('code')}: {e.get('title') or e.get('message') or ''}".strip()
            for e in status.get('errors') or []
        ) or 'failed, no reason given'
        updated = ours.update(status=Message.FAILED, error=reason[:500])
        logger.warning('WhatsApp message %s failed: %s', wamid, reason)
    else:
        earlier = PROGRESS[:PROGRESS.index(new)]
        updated = ours.filter(status__in=earlier).update(status=new)

    if not updated:
        logger.info(
            'WhatsApp status %s for %s matched nothing (unknown, or already further along)',
            word, wamid,
        )
        return

    # The spine: only receipts that changed something, once each.
    kind = STATUS_EVENTS.get(word)
    if kind and sent is not None:
        record(kind, actor=Event.PROVIDER,
               conversation=sent.conversation, customer=sent.conversation.customer,
               key=f'wa-status:{wamid}:{word}',
               payload={'message_id': sent.pk},
               reason=reason)



def _media_details(message):
    """(file name, mime type) of a media message, as WhatsApp sends them."""
    kind = message.get('type') or ''
    if kind not in MEDIA_TYPES:
        return '', ''
    media = message.get(kind) or {}
    return (media.get('filename') or '')[:255], (media.get('mime_type') or '')[:100]


def _keep_media(message):
    """Fetch the customer's file once the message is committed, before WhatsApp deletes it."""
    from apps.communications.tasks import fetch_whatsapp_media
    transaction.on_commit(lambda: fetch_whatsapp_media.delay(message.pk))


def _quoted(conversation, context):
    """The message a customer quoted when they swiped to reply on WhatsApp (8 Nov 2026)."""
    wamid = context.get('id') if isinstance(context, dict) else None
    if not wamid:
        return None
    return Message.objects.filter(conversation=conversation, external_id=wamid).first()


# A customer saying no to messages, in their own words (8 Nov 2026). It has to
# be the whole message: "stop the printing, I'll change the file" or "not
# interested in the A3" is about a job, never a no to being messaged.
OPT_OUT = re.compile(
    r"^\W*(please\s+)?(stop|unsubscribe|opt\s*out|no more (messages|msgs|texts)|"
    r"(do not|don'?t|dont) (message|text|contact|send)( me)?( again| anymore| any more)?|"
    r"stop (messaging|texting|sending)( me)?( messages)?|not interested|remove me)"
    r"(\s*,?\s*(please|thanks|thank you|sorry))?\W*$",
    re.IGNORECASE)


def _opt_out_if_asked(conversation, body):
    """Mark the chat no-marketing when the customer asks not to be messaged like this."""
    text = (body or '').strip()
    if not text or len(text) > 60 or not OPT_OUT.search(text):
        return False
    if not getattr(conversation, 'marketing_opt_out', False):
        type(conversation).objects.filter(pk=conversation.pk).update(marketing_opt_out=True)
        conversation.marketing_opt_out = True
        logger.info('Conversation %s asked not to receive marketing', conversation.pk)
    return True


# Meta's business-scoped user id: a country, a dot, then letters and digits.
USER_ID = re.compile(r'^[A-Z]{2}\.[A-Za-z0-9]+$')


def _conversation_for(phone, user_id, username=''):
    """
    The chat for this sender (9 Nov 2026): by user id first (it survives a
    hidden number), else by phone, else a new chat with no number. The user
    id, username and phone are kept up to date on it.
    """
    from django.db import IntegrityError
    chat = None
    if user_id:
        chat = (Conversation.objects.filter(channel=Conversation.WHATSAPP, contact_user_id=user_id)
                .order_by('-id').first())
    if chat is None and phone:
        chat, _ = Conversation.objects.get_or_create(branch=None, contact_phone=phone, channel=Conversation.WHATSAPP)
    if chat is None:
        chat = Conversation.objects.create(branch=None, contact_phone='', channel=Conversation.WHATSAPP,
                                           contact_user_id=user_id, contact_username=username or '')
    changed = []
    if user_id and chat.contact_user_id != user_id:
        chat.contact_user_id = user_id; changed.append('contact_user_id')
    if username and chat.contact_username != username:
        chat.contact_username = username; changed.append('contact_username')
    if changed:
        chat.save(update_fields=changed)
    if phone and not chat.contact_phone:
        try:
            with transaction.atomic():
                type(chat).objects.filter(pk=chat.pk).update(contact_phone=phone)
                chat.contact_phone = phone
        except IntegrityError:
            logger.info('Phone %s already has its own chat; chat %s keeps its user id', phone, chat.pk)
    return chat


def _tell_managers(event):
    """A customer's message that couldn't be recorded is never silent: every BM is told."""
    try:
        from apps.accounts.models import CustomUser
        from apps.notifications.services import notify
        names = set()
        for entry in event.payload.get('entry') or []:
            for change in entry.get('changes') or []:
                for c in (change.get('value') or {}).get('contacts') or []:
                    name = (c.get('profile') or {}).get('name')
                    if name:
                        names.add(name)
        who = ', '.join(sorted(names)) or 'a customer'
        for bm in CustomUser.objects.filter(role__name='BRANCH_MANAGER', is_active=True):
            notify(recipient=bm, verb='system', link='inbox',
                   message=f"A WhatsApp message from {who} couldn't be recorded (delivery {event.pk}). "
                           f"It has been kept, so it can be replayed.")
    except Exception:
        logger.exception('Could not tell the managers about delivery %s', getattr(event, 'pk', None))
