"""
The inbox, live (9 Nov 2026): when a message is saved (arriving, its file
ready, a reply, a delivery tick) or a chat changes (taken over, handed back),
every open portal is told on the live connection and refreshes the chat list
and that chat at once, instead of waiting for its next check.

WhatsApp chats belong to no single branch, so they are announced to every
branch; a branch's own chat only to that branch.
"""
import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def announce(conversation_id, branch_id=None):
    """Tell the portals that a chat changed, once the change is saved."""
    def send():
        try:
            from apps.core.broadcast import broadcast_invalidation
            from apps.organization.models import Branch
            events = ['conversations', f'conversation:{conversation_id}']
            branches = [branch_id] if branch_id else list(Branch.objects.values_list('id', flat=True))
            for branch in branches:
                broadcast_invalidation(branch, events)
        except Exception:
            logger.exception('Could not announce chat %s', conversation_id)
    transaction.on_commit(send)


@receiver(post_save, sender='communications.Message')
def _message_saved(sender, instance, **kwargs):
    # Every save of a message matters to the screen: new, its file ready, a tick.
    try:
        announce(instance.conversation_id, instance.conversation.branch_id)
    except Exception:
        logger.exception('Could not announce message %s', instance.pk)


# Saves that change nothing anyone sees (reading a chat) are never announced:
# announcing them made every open portal fetch again, which read it again... a loop.
QUIET = {'unread_count', 'updated_at'}


@receiver(post_save, sender='communications.Conversation')
def _conversation_saved(sender, instance, update_fields=None, **kwargs):
    if update_fields and set(update_fields) <= QUIET:
        return
    try:
        announce(instance.pk, instance.branch_id)
    except Exception:
        logger.exception('Could not announce chat %s', instance.pk)
