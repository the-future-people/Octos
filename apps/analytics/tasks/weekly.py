"""
Weekly risk scoring Celery task.
Full implementation in Session 3.
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def compute_weekly_risk(self, weekly_report_id):
    """
    Compute risk score for a weekly filing.
    Full implementation: Session 3 — Weekly Risk Engine.
    """
    try:
        logger.info('compute_weekly_risk: report_id=%s (stub — Session 3)', weekly_report_id)
    except Exception as e:
        logger.error('compute_weekly_risk failed for report %s: %s', weekly_report_id, e)
        raise self.retry(exc=e)