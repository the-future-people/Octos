from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task
def observe_station_timings():
    """
    Learn yesterday's actual work times from the job log.

    Nightly rather than on transition: a wrong timing does not need to be
    right within seconds, and analytics has no business in the path a
    cashier takes to confirm a payment.
    """
    from apps.production.services.timing_service import TimingService

    result = TimingService.observe_day()
    logger.info('observe_station_timings: %s', result)
    return result