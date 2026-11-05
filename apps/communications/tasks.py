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
def answer_whatsapp(conversation_id, trigger_id):
    """Octos considers a customer's message. All the rules are in assistant/brain."""
    from apps.communications.assistant import brain
    brain.respond(conversation_id, trigger_id)