"""
Clearing out what nobody completed.

Most carts are abandoned. That is expected and costs nothing except
disk: a banner's artwork is tens of megabytes, and an order nobody
finished holds it indefinitely unless something takes it away.

It also makes a promise true. Telling a customer we keep their cart for
seven days means nothing unless seven days is actually enforced, and a
cart that lives forever is a cart nobody can rely on either way.

What this must never touch is money.

An order someone has paid for is a job somebody is waiting for. An
order part-way through payment is worse — the customer is on Paystack's
page right now, or the webhook is late, and deleting it means taking
money for something that no longer exists. Age says nothing about
either: a slow webhook on an order created eight days ago is still a
real payment.

So the rule is not "old things go". It is "old things that nobody has
begun to pay for go", and everything else stays however old it looks.
"""

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


# Statuses that mean money is involved, now or already. Nothing in this
# set is ever swept, whatever its date says.
PROTECTED = (
    'AWAITING_PAYMENT',
    'PAID',
    'CONVERTED',
)


def sweep():
    """
    Remove expired carts and the artwork waiting on nothing.

    Safe to run repeatedly — a second run finds nothing left to do.
    Returns what it removed, so the nightly job can be seen to be
    working rather than merely scheduled.
    """
    return {
        'orders': _sweep_orders(),
        'staged': _sweep_staged(),
    }


def _sweep_orders():
    """
    Expired carts nobody has started paying for.

    A null expiry is left alone. Those rows predate the field, and
    deleting what we cannot date would be guessing with somebody's
    work.
    """
    from apps.storefront.models import OnlineOrder

    due = (
        OnlineOrder.objects
        .filter(expires_at__lt=timezone.now())
        .exclude(status__in=PROTECTED)
        .exclude(paid_at__isnull=False)
        .exclude(job__isnull=False)
    )

    removed = 0
    for order in due.prefetch_related('files'):
        try:
            # The files go first and deliberately, rather than relying
            # on the cascade: a database row disappearing does not take
            # thirty megabytes off disk with it.
            for record in order.files.all():
                record.file.delete(save=False)

            number = order.order_number
            order.delete()
            removed += 1
            logger.info('Swept expired order %s', number)
        except Exception:
            # One bad row must not stop the rest. A file that cannot be
            # deleted — already gone, storage unreachable — leaves its
            # order for the next run rather than failing the whole
            # sweep.
            logger.warning(
                'Could not sweep order %s', order.pk, exc_info=True,
            )

    return removed


def _sweep_staged():
    """
    Artwork checked and never committed.

    Most of these. A customer who checks a file and changes their mind
    is the common case, and the staging exists precisely so that costs
    them nothing — which means it has to cost us nothing either.
    """
    from apps.storefront.models import StagedUpload

    due = StagedUpload.objects.filter(expires_at__lt=timezone.now())

    removed = 0
    for staged in due:
        try:
            staged.file.delete(save=False)
            staged.delete()
            removed += 1
        except Exception:
            logger.warning(
                'Could not sweep staged upload %s', staged.pk, exc_info=True,
            )

    return removed