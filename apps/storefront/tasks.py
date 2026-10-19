from celery import shared_task
import logging

logger = logging.getLogger(__name__)

@shared_task
def sweep_storefront():
    """
    Nightly. Removes expired carts and artwork nobody committed.

    A thin wrapper, like the sheet tasks: the work lives in a command
    so it can be run by hand when something needs clearing before the
    night comes round.
    """
    from django.core.management import call_command
    call_command('sweep_storefront')

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def convert_order(self, order_id):
    """
    Turn a paid order into work.

    Retried, because the alternative is money taken and nothing made.
    Three attempts a minute apart covers a database hiccup or a branch
    whose sheet is mid-rollover; past that the sweep picks it up and a
    person should look.
    """
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.conversion import convert

    order = OnlineOrder.objects.filter(pk=order_id).first()
    if order is None:
        return

    try:
        job = convert(order)
    except Exception as problem:
        raise self.retry(exc=problem)

    return job.job_number if job else None


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def tell_customer_ready(self, job_id):
    """
    The text a customer is actually waiting for: their order is ready.

    Queued on commit when the floor marks a job DONE, so a move that
    rolls back never tells anyone anything, and the coordinator's tap
    never waits on mNotify.

    Online orders only. A walk-in has no order, no tracking link and has
    not been asked whether it wants texts; that is a separate decision.

    Retried five minutes apart. A late ready text is fine; a missing one
    is a customer who never comes to collect.
    """
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.messages import ready_text
    from apps.storefront.services.sms import send_sms

    order = (
        OnlineOrder.objects
        .select_related('lead')
        .filter(job_id=job_id)
        .first()
    )
    if order is None or not order.lead_id:
        return None

    try:
        # The app first; an SMS only if no phone of theirs was reached.
        from apps.storefront.services.notify import tell
        branch = order.branch.name if order.branch_id else 'the branch'
        tell(
            order, 'ready', 'Ready to collect',
            f'Your order {order.order_number} is ready at {branch}.',
            sms_text=ready_text(order), text_with=send_sms,
        )
    except Exception as problem:
        raise self.retry(exc=problem)

    return order.order_number


@shared_task
def convert_stragglers():
    """
    Paid orders the floor never heard about.

    A task can die, a worker can restart mid-flight, and a webhook can
    arrive while the database is briefly unreachable. This is the net
    under all of that: money that arrived and never became work is the
    worst state in the system, and it should never last a night.
    """
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.conversion import convert

    stranded = OnlineOrder.objects.filter(
        status=OnlineOrder.Status.PAID,
        job__isnull=True,
        branch__isnull=False,
    )

    made = 0
    for order in stranded:
        try:
            if convert(order):
                made += 1
        except Exception:
            logger.error(
                'Straggler %s still will not convert',
                order.order_number, exc_info=True,
            )

    if made:
        logger.warning(
            '%d paid order(s) had to be converted by the sweep', made,
        )
    return made