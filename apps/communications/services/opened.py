"""
A person opened a customer's file (11 Nov 2026).

Recorded on the spine as file.opened, once per file, with who opened it. It
discharges the visit's files obligation (no more questions about those files)
and is a presence anchor: a person has them (apps/spine/presence.py).

Only an explicit open counts (the inbox's Open, ?download=1), not a photo
appearing in a thread someone is looking at.
"""
from apps.communications.models import Message


def file_opened(message, user):
    """Record that this person opened this customer's file. Safe to call twice."""
    if message is None or message.direction != Message.INBOUND:
        return None
    from apps.spine import kinds
    from apps.spine.models import Event
    from apps.spine.recorder import record
    conversation = message.conversation
    name = getattr(user, 'full_name', '') or getattr(user, 'email', '') or 'Staff'
    event, _ = record(kinds.FILE_OPENED, actor=Event.STAFF, actor_user=user,
                      conversation=conversation, customer=conversation.customer,
                      key=f'file-opened:{message.pk}',
                      payload={'message_id': message.pk, 'file': message.media_name or ''},
                      reason=f'{name} opened {message.media_name or "the file"}.')
    return event


FOCUS_SECONDS = 60      # the inbox re-fetches an open chat every few seconds
RECORD_EVERY = 600      # the spine hears of it at most every 10 minutes per person


def chat_opened(conversation, user):
    """
    A person has this chat open in the inbox (14 Nov 2026). Called each time
    the inbox fetches it. Marks the chat "in focus" for a minute, in the cache,
    so the frequent fetches cost nothing; and records chat.opened on the spine
    at most every 10 minutes per person, so the record is honest without a
    row every few seconds.
    """
    from django.core.cache import cache
    from django.utils import timezone
    user_id = getattr(user, 'pk', None) or 0
    cache.set(_focus_key(conversation.pk), user_id or True, FOCUS_SECONDS)
    if not cache.add(f'chat-opened-recorded:{conversation.pk}:{user_id}', True, RECORD_EVERY):
        return None
    from apps.spine import kinds
    from apps.spine.models import Event
    from apps.spine.recorder import record
    name = getattr(user, 'full_name', '') or getattr(user, 'email', '') or 'Staff'
    stamp = timezone.now().strftime('%Y%m%d%H%M')
    event, _ = record(kinds.CHAT_OPENED, actor=Event.STAFF, actor_user=user,
                      conversation=conversation, customer=conversation.customer,
                      key=f'chat-opened:{conversation.pk}:{user_id}:{stamp}',
                      reason=f'{name} had the chat open.')
    return event


def in_focus(conversation_id):
    """True while someone at Farhat has this chat open in the inbox."""
    from django.core.cache import cache
    return bool(cache.get(_focus_key(conversation_id)))


def _focus_key(conversation_id):
    return f'chat-focus:{conversation_id}'
