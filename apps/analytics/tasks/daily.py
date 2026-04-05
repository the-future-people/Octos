"""
Daily risk analysis Celery task.
Triggered by on_sheet_saved signal when sheet status → CLOSED.
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def analyse_daily_risk(self, sheet_id):
    """
    Analyse a closed daily sheet for risk signals.
    Creates DailyRiskReport and DailyRiskFlag records.
    Routes alerts to RM if score >= 40 or any CRITICAL flag.
    """
    try:
        from apps.finance.models import DailySalesSheet
        from apps.analytics.engines.daily_risk_engine import DailyRiskEngine

        sheet  = DailySalesSheet.objects.select_related('branch').get(pk=sheet_id)
        engine = DailyRiskEngine(sheet)
        report = engine.analyse()

        logger.info(
            'analyse_daily_risk complete: sheet=%s score=%s flags=%s',
            sheet_id, report.risk_score, report.total_flags,
        )
        return {
            'sheet_id'  : sheet_id,
            'risk_score': report.risk_score,
            'flags'     : report.total_flags,
        }

    except DailySalesSheet.DoesNotExist:
        logger.error('analyse_daily_risk: sheet %s not found', sheet_id)
        return None

    except Exception as e:
        logger.error('analyse_daily_risk failed for sheet %s: %s', sheet_id, e, exc_info=True)
        raise self.retry(exc=e)