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
