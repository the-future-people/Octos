"""
What a trade partner pays (23 Nov 2026).

  - 6% under the walk-in price on every job: GHS 47 where a walk-in pays 50.
  - 10% instead on the partner's first job, and on one job after every 20.
    Rewards replace the 6% on that job; they never stack.
  - Never on a line already at its minimum charge: the minimum is the
    least that work costs us, so nothing comes off it.
  - The payment provider's fee is the partner's, on top, as its own line.

Only paid jobs worth GHS 30 or more count toward the milestones (the 20,
and the branded wrap at 15), so twenty small jobs can't buy 10% off a big
one. Worked out on the server on every save while the order is open, and
frozen once it is paid.
"""
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal

from django.db.models import F

TRADE = Decimal('0.06')
REWARD = Decimal('0.10')
EVERY = 20                  # 10% off one job after every 20
WRAP_AT = 15                # the branded wrap
COUNTS_FROM = Decimal('30.00')
CENT = Decimal('0.01')

FIRST, EVERY_20 = 'FIRST', 'EVERY_20'
REASONS = {
    '': 'Trade price, 6% off',
    FIRST: 'Trade partner first job, 10% off',
    EVERY_20: 'Trade partner reward, 10% off',
}


def counted_jobs(partner, excluding=None):
    """Paid partner orders worth GHS 30 or more: what the milestones count."""
    from apps.storefront.models import OnlineOrder
    found = (OnlineOrder.objects.filter(partner=partner, paid_at__isnull=False)
             .annotate(work=F('total') - F('processing_fee')).filter(work__gte=COUNTS_FROM))
    if excluding is not None:
        found = found.exclude(pk=excluding)
    return found.count()


def reward_for(count):
    """The reward on the next job, given how many have counted so far."""
    if count == 0:
        return FIRST
    if count % EVERY == 0:
        return EVERY_20
    return ''


def progress(partner):
    """For the dashboard: how far to the wrap and to the next 10%."""
    count = counted_jobs(partner)
    return {
        'jobs': count,
        'wrap': {'at': WRAP_AT, 'done': min(count, WRAP_AT), 'earned': count >= WRAP_AT},
        'reward': {'every': EVERY, 'done': count % EVERY if count else 0,
                   'next_is_reward': reward_for(count) != ''},
    }


def fee_on(amount, rate=None):
    """
    The provider's fee, carried by the partner: grossed up so that what
    reaches Farhat after Paystack's cut is the work's own price.
    """
    from apps.storefront.services.fees import PAYSTACK_GH_RATE
    rate = rate if rate is not None else PAYSTACK_GH_RATE
    if amount <= 0:
        return Decimal('0.00')
    gross = (amount / (1 - rate)).quantize(CENT, rounding=ROUND_UP)
    return gross - amount


def settle(order):
    """
    Set the order's money from its lines: full_total, the discount and why,
    the reward, the fee and what is charged. Changes the instance; the
    caller saves (OnlineOrder.save calls this itself).
    """
    lines = order.line_items or []
    work = sum((Decimal(str(line.get('total') or 0)) for line in lines), Decimal('0.00'))
    open_to_discount = sum((Decimal(str(line.get('total') or 0)) for line in lines
                            if not line.get('at_minimum')), Decimal('0.00'))

    reward = reward_for(counted_jobs(order.partner, excluding=order.pk)) if work > 0 else ''
    rate = REWARD if reward else TRADE
    discount = (open_to_discount * rate).quantize(CENT, rounding=ROUND_HALF_UP)

    after = work - discount
    order.full_total = work
    order.discount_amount = discount
    order.discount_reason = REASONS[reward] if discount else ''
    order.partner_reward = reward if discount else ''
    order.processing_fee = fee_on(after)
    order.total = after + order.processing_fee
    return order
