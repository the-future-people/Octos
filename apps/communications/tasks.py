"""
Worker tasks for communications.

deliver_whatsapp runs whatever whatsapp_outbound.send_text queued, after
the request that queued it has committed. All the logic lives in the
service; this file only puts it on the worker.

No automatic retries: a failed send is recorded as FAILED with Meta's
reason, in the thread, where staff can see it. A retry that might send
the same message twice is worse than a failure everyone can see.
"""
from asyncio.log import logger

from celery import shared_task

from apps.communications.services import whatsapp_outbound


@shared_task
def deliver_whatsapp(message_id):
    whatsapp_outbound.deliver(message_id)

@shared_task
def watch_handovers():
    """
    Every minute: a customer waiting 30 minutes on a conversation a person
    has gets that person reminded; 10 minutes after an ignored reminder,
    Octos takes the conversation back. The rules live in services/handover.
    """
    from apps.communications.services import handover

    reminded, taken_back = handover.watch()
    if reminded or taken_back:
        logger.info('Handover watch: %s reminded, %s taken back', reminded, taken_back)

@shared_task
def flag_quiet_remote():
    """
    Every 5 minutes: a customer who sent a file from outside the shop and went
    quiet with no job made goes to "Needs you" (services/quiet_remote.py).
    """
    from apps.communications.services.quiet_remote import flag_quiet

    flagged = flag_quiet()
    if flagged:
        logger.info('Flagged %s quiet remote chat(s) for a person', flagged)

@shared_task
def answer_whatsapp(conversation_id, trigger_id):
    """Octos considers a customer's message. All the rules are in assistant/brain."""
    from apps.communications.assistant import brain
    brain.respond(conversation_id, trigger_id)

@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def fetch_whatsapp_media(self, message_id):
    """
    Keep a customer's file before WhatsApp deletes it. A network failure
    tries again, a minute apart; a file that is gone or too big is logged
    and left (the inbox says it wasn't saved).
    """
    import requests
    from apps.communications.services import whatsapp_media
    try:
        whatsapp_media.fetch(message_id)
    except whatsapp_media.MediaError:
        logger.warning('WhatsApp media for message %s cannot be kept', message_id, exc_info=True)
        whatsapp_media.mark_failed(message_id, 'gone')
    except requests.RequestException as exc:
        if self.request.retries >= self.max_retries:
            whatsapp_media.mark_failed(message_id, 'network')
            raise
        raise self.retry(exc=exc)
    except Exception:
        # Anything else (a bug, the database refusing) must never leave staff
        # watching "Receiving the file..." for ever (15 Nov 2026).
        whatsapp_media.mark_failed(message_id, 'error')
        raise

@shared_task
def show_whatsapp_typing(message_id):
    """'typing...' on a customer's message the moment it arrives, if Octos will answer."""
    from apps.communications.assistant import brain
    brain.show_typing_for(message_id)

# ── The owner's private line (18 Nov 2026) ──────────────────────────────────

@shared_task
def deliver_owner_message(pk):
    from apps.communications.services import owner_line
    owner_line.deliver(pk)


@shared_task
def answer_owner(pk):
    from apps.communications.services import owner_line
    owner_line.answer(pk)


@shared_task
def owner_brief():
    """The morning brief, 7:30 every day."""
    from apps.communications.services import owner_line
    owner_line.send_brief()


@shared_task
def owner_close():
    """The day's close, 9:00pm every day, after sign-off."""
    from apps.communications.services import owner_line
    owner_line.send_close()


@shared_task
def report_watched_chat(conversation_id, trigger_id):
    """A chat the owner asked Octos to watch: report the customer's reply (19 Nov 2026)."""
    from apps.communications.services import owner_watch
    owner_watch.report(conversation_id, trigger_id)


@shared_task
def owner_reminders():
    """Every minute: the owner's "check back" and "remind me" that are due (19 Nov 2026)."""
    from apps.communications.services import owner_watch
    owner_watch.fire_due()


@shared_task
def run_sandbox(case_id):
    """A 'can you do this?' look from the website (services/sandbox.py)."""
    from apps.communications.models import SandboxCase
    from apps.communications.services import sandbox
    case = SandboxCase.objects.filter(pk=case_id).first()
    if case is not None and case.status == SandboxCase.QUEUED:
        sandbox.run(case)
