"""
Daily risk analysis Celery task.
Triggered by on_sheet_saved signal when sheet status → CLOSED.
Full implementation in Session 2.
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def analyse_daily_risk(self, sheet_id):
    """
    Analyse a closed daily sheet for risk signals.
    Creates DailyRiskReport and DailyRiskFlag records.
    
    Full implementation: Session 2 — Daily Risk Engine.
    """
    try:
        logger.info('analyse_daily_risk: sheet_id=%s (stub — Session 2)', sheet_id)
        # TODO: implement in Session 2
    except Exception as e:
        logger.error('analyse_daily_risk failed for sheet %s: %s', sheet_id, e)
        raise self.retry(exc=e)