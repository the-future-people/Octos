import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def close_quiet_visits():
    """Every 10 minutes: close visits quiet for over 2 hours (apps/spine/visits.py)."""
    from apps.spine.visits import close_quiet
    closed = close_quiet()
    if closed:
        logger.info('Closed %s quiet visit(s)', closed)
