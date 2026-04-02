"""
Monthly close summary compilation Celery task.
Triggered by MonthlyClose status → SUBMITTED signal.
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def compile_monthly_summary(self, monthly_close_id):
    """
    Compile MonthlyCloseSummary from all daily and weekly risk data.
    Assigns Finance reviewer and sends notifications.
    """
    try:
        from apps.finance.models import MonthlyClose
        from apps.analytics.engines.monthly_engine import MonthlyEngine

        close  = MonthlyClose.objects.select_related('branch').get(pk=monthly_close_id)
        engine = MonthlyEngine(close)
        summary = engine.compile()

        logger.info(
            'compile_monthly_summary complete: close=%s risk=%s flags=%s',
            monthly_close_id,
            summary.overall_risk_score,
            len(summary.all_flags),
        )
        return {
            'close_id'   : monthly_close_id,
            'risk_score' : summary.overall_risk_score,
            'flag_count' : len(summary.all_flags),
            'reviewer'   : summary.finance_reviewer.full_name
                           if summary.finance_reviewer else None,
        }

    except MonthlyClose.DoesNotExist:
        logger.error('compile_monthly_summary: close %s not found', monthly_close_id)
        return None

    except Exception as e:
        logger.error(
            'compile_monthly_summary failed for close %s: %s',
            monthly_close_id, e, exc_info=True
        )
        raise self.retry(exc=e)