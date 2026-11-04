"""
Worker tasks for communications.

deliver_whatsapp runs whatever whatsapp_outbound.send_text queued, after
the request that queued it has committed. All the logic lives in the
service; this file only puts it on the worker.

No automatic retries: a failed send is recorded as FAILED with Meta's
reason, in the thread, where staff can see it. A retry that might send
the same message twice is worse than a failure everyone can see.
"""
from celery import shared_task

from apps.communications.services import whatsapp_outbound


@shared_task
def deliver_whatsapp(message_id):
    whatsapp_outbound.deliver(message_id)