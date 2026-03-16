"""
Notification service — the single point of entry for creating notifications.

Usage anywhere in the codebase:

    from apps.notifications.services import notify, notify_many

    notify(
        recipient=user,
        verb='job_created',
        message='A new job was created: Business Cards #42',
        link='/portal/jobs/',
        actor=request.user,   # optional
    )

    notify_many(
        recipients=[user1, user2],
        verb='job_routed',
        message='Job #42 has been routed to Westland Branch',
        link='/portal/jobs/',
    )
"""

import logging
from typing import Optional

from django.contrib.auth import get_user_model

from .models import Notification

logger = logging.getLogger(__name__)
User = get_user_model()


def notify(
    recipient,
    verb: str,
    message: str,
    link: str = '',
    actor=None,
) -> Optional[Notification]:
    """
    Create a single notification.
    Returns the Notification instance or None if creation failed.
    """
    if recipient is None:
        logger.warning('notify() called with recipient=None, skipping.')
        return None

    # Never notify a user about their own action
    if actor is not None and actor.pk == recipient.pk:
        return None

    try:
        notif = Notification.objects.create(
            recipient=recipient,
            actor=actor,
            verb=verb,
            message=message,
            link=link,
        )
        logger.debug('Notification created: %s → %s', verb, recipient)
        return notif
    except Exception as exc:
        logger.error('Failed to create notification: %s', exc)
        return None


def notify_many(
    recipients,
    verb: str,
    message: str,
    link: str = '',
    actor=None,
) -> list:
    """
    Create a notification for each recipient in the iterable.
    Skips None recipients and actor self-notifications.
    Returns list of created Notification instances.
    """
    created = []
    for recipient in recipients:
        notif = notify(
            recipient=recipient,
            verb=verb,
            message=message,
            link=link,
            actor=actor,
        )
        if notif:
            created.append(notif)
    return created


def get_unread_count(user) -> int:
    """Return the number of unread notifications for a user."""
    return Notification.objects.filter(recipient=user, is_read=False).count()


def mark_all_read(user) -> int:
    """Mark all notifications as read for a user. Returns count updated."""
    return Notification.objects.filter(
        recipient=user, is_read=False
    ).update(is_read=True)