"""
Weekly risk scoring Celery task.
Triggered by WeeklyReport status → LOCKED signal.
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def compute_weekly_risk(self, weekly_report_id):
    """
    Compute risk score for a weekly filing.
    Creates WeeklyRiskScore and WeeklyRiskFlag records.
    Assigns Finance reviewer if score >= 50 or any CRITICAL flag.
    """
    try:
        from apps.finance.models import WeeklyReport
        from apps.analytics.engines.weekly_risk_engine import WeeklyRiskEngine

        report = WeeklyReport.objects.select_related('branch').get(pk=weekly_report_id)
        engine = WeeklyRiskEngine(report)
        score  = engine.analyse()

        logger.info(
            'compute_weekly_risk complete: report=%s score=%s requires_finance=%s',
            weekly_report_id, score.risk_score, score.requires_finance_review,
        )
        return {
            'report_id'        : weekly_report_id,
            'risk_score'       : score.risk_score,
            'requires_finance' : score.requires_finance_review,
        }

    except WeeklyReport.DoesNotExist:
        logger.error('compute_weekly_risk: report %s not found', weekly_report_id)
        return None

    except Exception as e:
        logger.error('compute_weekly_risk failed for report %s: %s', weekly_report_id, e, exc_info=True)
        raise self.retry(exc=e)