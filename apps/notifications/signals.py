"""
Notification signals.
Wired into Job, Conversation, and Message post_save events.
Loaded via NotificationsConfig.ready() in apps.py.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

from .services import notify, notify_many

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Jobs
# ─────────────────────────────────────────────────────────────

def _wire_job_signals():
    try:
        from apps.jobs.models import Job, JobStatusLog

        @receiver(post_save, sender=Job, dispatch_uid='notif_job_created')
        def on_job_created(sender, instance, created, **kwargs):
            if not created:
                return
            # Notify the branch manager of the branch this job belongs to
            recipients = _branch_managers(instance.branch)
            notify_many(
                recipients=recipients,
                verb='job_created',
                message=f'New job created: {instance.title or instance.reference}',
                link='/portal/jobs/',
            )

        @receiver(post_save, sender=JobStatusLog, dispatch_uid='notif_job_status')
        def on_job_status_changed(sender, instance, created, **kwargs):
            if not created:
                return
            job = instance.job
            recipients = _branch_managers(job.branch)
            notify_many(
                recipients=recipients,
                verb='job_status_changed',
                message=(
                    f'Job {job.reference or job.title} '
                    f'moved to {instance.new_status}'
                ),
                link='/portal/jobs/',
                actor=instance.changed_by if hasattr(instance, 'changed_by') else None,
            )

    except Exception as exc:
        logger.warning('Could not wire job signals: %s', exc)


# ─────────────────────────────────────────────────────────────
# Communications
# ─────────────────────────────────────────────────────────────

def _wire_comms_signals():
    try:
        from apps.communications.models import Message, Conversation

        @receiver(post_save, sender=Message, dispatch_uid='notif_message_received')
        def on_message_received(sender, instance, created, **kwargs):
            if not created:
                return
            # Only notify for inbound messages
            if hasattr(instance, 'direction') and instance.direction == 'OUTBOUND':
                return

            conversation = instance.conversation
            recipients   = _conversation_assignees(conversation)
            notify_many(
                recipients=recipients,
                verb='message_received',
                message=(
                    f'New message from '
                    f'{getattr(conversation, "customer_name", "a customer")}'
                ),
                link='/portal/inbox/',
            )

        @receiver(post_save, sender=Conversation, dispatch_uid='notif_conversation_assigned')
        def on_conversation_assigned(sender, instance, created, **kwargs):
            if created:
                return
            # Fire when assigned_to changes
            if not hasattr(instance, '_previous_assigned_to'):
                return
            if instance.assigned_to and instance.assigned_to != instance._previous_assigned_to:
                notify(
                    recipient=instance.assigned_to,
                    verb='conversation_assigned',
                    message='A conversation has been assigned to you.',
                    link='/portal/inbox/',
                )

    except Exception as exc:
        logger.warning('Could not wire comms signals: %s', exc)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _branch_managers(branch):
    """Return all active users in a branch who have a branch manager role."""
    if branch is None:
        return []
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return list(
            User.objects.filter(
                branch=branch,
                is_active=True,
                role__name__icontains='branch manager',
            )
        )
    except Exception:
        return []


def _conversation_assignees(conversation):
    """Return assigned user of a conversation, or branch managers as fallback."""
    recipients = []
    if hasattr(conversation, 'assigned_to') and conversation.assigned_to:
        recipients.append(conversation.assigned_to)
    elif hasattr(conversation, 'branch') and conversation.branch:
        recipients = _branch_managers(conversation.branch)
    return recipients


# ─────────────────────────────────────────────────────────────
# Entry point — called from apps.py ready()
# ─────────────────────────────────────────────────────────────

def connect_all():
    _wire_job_signals()
    _wire_comms_signals()
    logger.info('Notification signals connected.')