"""
Monthly close summary compilation Celery task.
Full implementation in Session 4.
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def compile_monthly_summary(self, monthly_close_id):
    """
    Compile MonthlyCloseSummary from all daily and weekly risk data.
    Full implementation: Session 4 — Monthly Close Rebuild.
    """
    try:
        logger.info(
            'compile_monthly_summary: close_id=%s (stub — Session 4)',
            monthly_close_id
        )
    except Exception as e:
        logger.error(
            'compile_monthly_summary failed for close %s: %s',
            monthly_close_id, e
        )
        raise self.retry(exc=e)