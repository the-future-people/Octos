from celery import shared_task
import logging
logger = logging.getLogger(__name__)

@shared_task
def expire_drafts():
    from django.core.management import call_command
    call_command('expire_drafts')