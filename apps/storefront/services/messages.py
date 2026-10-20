"""
What we text a customer, and how long it is allowed to be.

An SMS carries 160 characters. Past that it splits in two, costs
double, and arrives as a message that reads worse than the one that
fit. So these are written to a budget rather than written and hoped
over — and there is a test that fails if one grows.

The link is the short code rather than the access token: the token
runs to 43 characters and a URL carrying it leaves no room for the
message around it.

Everything here is a plain function returning a string. Sending is
somebody else's job, so a message can be checked without a network.
"""

from decimal import Decimal

from django.conf import settings

# Where the storefront lives. Without the scheme — a phone linkifies
# it either way, and eight characters of "https://" is a tenth of the
# message.
STOREFRONT = getattr(settings, 'STOREFRONT_HOST', 'print-octos.vercel.app')

# One message. The test that enforces this is the reason it stays one.
LIMIT = 160


def payment_text(order):
    """
    Sent the moment an order is paid for and the floor has it.

    Three things, in the order a customer cares about them: the money
    is confirmed, here is when and where, and here is how to watch it.
    """
    lines = [
        f'Paid, thank you. Order {order.order_number}, '
        f'GHS {_money(order.total)}.'
    ]

    when = _ready(order)
    where = _branch_name(order)

    if when and where:
        lines.append(f'Ready about {when} at {where}.')
    elif where:
        lines.append(f'Collect at {where}.')
    elif when:
        lines.append(f'Ready about {when}.')

    lines.append(f'Track it: {STOREFRONT}/t/{order.short_code}')

    return _fit(' '.join(lines), order)


def ready_text(order):
    """
    Sent when the floor marks it done.

    The one message a customer is actually waiting for, so it says the
    thing first and explains second.
    """
    where = _branch_name(order) or 'the shop'
    return _fit(
        f'Your order is ready. {order.order_number} — collect at {where}, PIN {order.collection_pin}. '
        f'{STOREFRONT}/t/{order.short_code}',
        order,
    )


def _fit(text, order):
    """
    Inside one message, whatever the branch is called.

    A long branch name is the thing most likely to push this over, so
    that is what gives way — the link and the order number are what
    the message is for.
    """
    if len(text) <= LIMIT:
        return text

    # Drop the branch name and let the link carry the detail. Somebody
    # who taps it sees where to collect; somebody who does not still
    # has their order number.
    short = (
        f'Paid, thank you. {order.order_number}, GHS {_money(order.total)}. '
        f'Track: {STOREFRONT}/t/{order.short_code}'
    )
    return short[:LIMIT]


def _money(amount):
    return f'{Decimal(amount or 0):.2f}'


def _branch_name(order):
    """
    The branch, without the word "Branch" on the end.

    "Ready 4pm at Westland Branch" spends six characters saying what
    the sentence already said.
    """
    if not order.branch_id:
        return None

    name = order.branch.name or ''
    if name.endswith(' Branch'):
        name = name[:-7]
    return name.strip() or None


def _ready(order):
    """
    When, in the fewest characters that are still clear.

    "4:10pm today" rather than "around 4:10 PM on Monday 12 October" —
    the second is more precise and the first is what somebody reads.
    """
    if not order.promised_for:
        return None

    from django.utils import timezone

    at = timezone.localtime(order.promised_for)
    now = timezone.localtime()

    clock = at.strftime('%-I:%M%p').lower()

    if at.date() == now.date():
        return f'{clock} today'
    if (at.date() - now.date()).days == 1:
        return f'{clock} tomorrow'
    return f'{at.strftime("%a")} {clock}'