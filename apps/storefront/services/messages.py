"""
What we text a customer, and how long it is allowed to be.

An SMS carries 160 characters. Past that it splits in two, costs
double, and arrives as a message that reads worse than the one that
fit. So these are written to a budget rather than written and hoped
over, and there is a test that fails if one grows.

They are written the way the person at the counter would say it: the
customer's first name where we have a real one, what they ordered
rather than a code, and a short reference they can read out on the
phone. The full job number stays on the receipt and every staff screen.

Each text has a warm form and plainer fallbacks. The first that fits
is sent: the greeting gives way first, then the branch, never the
reference, the PIN or the link.

Everything here is a plain function returning a string. Sending is
somebody else's job, so a message can be checked without a network.
"""

from decimal import Decimal

from django.conf import settings

# Where the storefront lives. Without the scheme: a phone linkifies it
# either way, and "https://" is a twentieth of the message.
STOREFRONT = getattr(settings, 'STOREFRONT_HOST', 'print-octos.vercel.app')

# One message. The test that enforces this is the reason it stays one.
LIMIT = 160

# What a name field holds when nobody gave a name.
NOT_NAMES = {
    'customer', 'walkin', 'walk', 'guest', 'unknown', 'na', 'none',
    # Everyday words typed into a name box instead of a name.
    'no', 'yes', 'ok', 'on', 'in', 'at', 'the', 'my', 'me', 'hi', 'hello',
    'test', 'call', 'see', 'whatsapp', 'whatsup',
}


# ── The texts ────────────────────────────────────────────────

def payment_text(order):
    """An online order paid for: thanks, when and where, and the link."""
    name, what, ref = _first_name(order), _what(order), _ref(order)
    money = f'GHS {_money(order.total)}'
    when, where = _ready(order), _branch_name(order)
    link = f'Track: {STOREFRONT}/t/{order.short_code}'

    if when and where:
        timing = f'Ready about {when} at {where}.'
    elif where:
        timing = f'Collect at {where}.'
    elif when:
        timing = f'Ready about {when}.'
    else:
        timing = ''

    hello = f'Hi {name}, thank you!' if name else 'Thank you!'
    body = f'{_cap(what)} is in good hands (ref {ref}, {money}).'
    return _first_that_fits(
        _join(hello, body, timing, link),
        _join('Thank you!', body, timing, link),
        _join('Thank you!', body, f'Ready about {when}.' if when else '', link),
        _join(f'Paid, thank you (ref {ref}).', link),
    )


def counter_paid_text(order, balance=None):
    """A counter production job paid enough to start: we have it, when, what is left to pay."""
    name, what, ref = _first_name(order), _what(order), _ref(order)
    when = _ready(order)
    link = f'Track: {STOREFRONT}/t/{order.short_code}'
    owing = Decimal(balance or 0)

    if when and owing > 0:
        timing = f'Ready about {when}, balance GHS {_money(owing)} on collection.'
    elif when:
        timing = f'Ready about {when}.'
    elif owing > 0:
        timing = f"We'll text you when it's ready. Balance GHS {_money(owing)} on collection."
    else:
        timing = "We'll text you when it's ready."

    lead = f'Hi {name}, {what}' if name else f'Thank you! {_cap(what)}'
    return _first_that_fits(
        _join(f'{lead} is in good hands (ref {ref}).', timing, link),
        _join(f'{_cap(what)} is in good hands (ref {ref}).', timing, link),
        _join(f'Received (ref {ref}).', timing),
    )


def ready_text(order):
    """The one a customer is waiting for: it is ready, where, and the PIN to collect."""
    name, what = _first_name(order), _what(order)
    where = _branch_name(order) or 'the shop'
    pin = order.collection_pin
    link = f'{STOREFRONT}/t/{order.short_code}'

    hello = f'Good news, {name}!' if name else 'Good news!'
    return _first_that_fits(
        _join(hello, f'{_cap(what)} is ready. Come for it at {where} with PIN {pin}.', link),
        _join('Good news!', f'{_cap(what)} is ready. Come for it at {where} with PIN {pin}.', link),
        _join(f'{_cap(what)} is ready. Collect with PIN {pin}.', link),
    )


def late_text(order, when):
    """We are late on our own promise: own it, give the new time."""
    name, what = _first_name(order), _what(order)
    sorry = f'Sorry {name},' if name else 'Sorry,'
    return _first_that_fits(
        _join(f'{sorry} {what} is taking longer than we promised.',
              f"New time: about {when}. We're on it."),
        _join(f'Sorry, {what} is taking longer than we promised.', f'New time: about {when}.'),
    )


def changed_text(order, when):
    """The customer changed the job: thank them, give the new time. Not our delay, so no apology."""
    name, what = _first_name(order), _what(order)
    thanks = f'Thanks {name},' if name else 'Thanks,'
    return _first_that_fits(
        _join(f"{thanks} we've got your change.", f'{_cap(what)} will now be ready about {when}.'),
        _join(f'{_cap(what)} will now be ready about {when}.'),
    )


def code_text(code):
    """The sign-in code for the Print Octos app."""
    return f"Your Print Octos code is {code}. It's good for 10 minutes. Please don't share it with anyone."


# ── The pieces ───────────────────────────────────────────────

def _first_name(order):
    """
    The customer's first name, only when it looks like one. Junk typed
    into the name box ("On whatsup") or a placeholder ("Customer") gives
    no name, and the greeting drops rather than reading strangely.
    """
    lead = getattr(order, 'lead', None)
    field = (getattr(lead, 'first_name', '') or '').strip() if lead else ''
    # Judge the whole field, not just its first word: "On whatsup" starts
    # with a word that could pass, and "Hi On," is worse than no greeting.
    words = field.split()
    if not words or len(words) > 3:
        return None
    if any(not w.isalpha() or w.lower() in NOT_NAMES for w in words):
        return None
    first = words[0]
    if not 2 <= len(first) <= 12:
        return None
    return first[:1].upper() + first[1:].lower()


def _what(order):
    """
    What they ordered, as they would say it: "your banner". Several
    items, more than one of it, or a name that would read like a code
    ("A4 Color Printing 1-sided") is simply "your order".
    """
    lines = order.line_items or []
    if len(lines) != 1:
        return 'your order'
    line = lines[0] or {}
    name = (line.get('service_name') or '').strip()
    try:
        quantity = int(line.get('quantity') or 1)
    except (TypeError, ValueError):
        quantity = 1
    if quantity != 1 or not name or len(name) > 18 or any(c.isdigit() for c in name):
        return 'your order'
    return f'your {name.lower()}'


def _ref(order):
    """
    A reference short enough to read out on the phone: the number the
    customer was given, without its prefix or leading zeros. A counter
    job's number (FP-WLB-2026-05629 is 5629), an online order's own
    (ORD-2026-00043 is 43). The job search matches on "contains", so
    the counter finds it from this.
    """
    reference = order.payment_reference or ''
    number = reference.split(':', 1)[1] if reference.startswith('COUNTER:') else (order.order_number or '')
    tail = number.rsplit('-', 1)[-1].lstrip('0')
    return tail or number


def _first_that_fits(*candidates):
    for text in candidates:
        if text and len(text) <= LIMIT:
            return text
    return (candidates[-1] or '')[:LIMIT]


def _join(*parts):
    return ' '.join(p for p in parts if p)


def _cap(text):
    return text[:1].upper() + text[1:]


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

    "4:10pm today" rather than "around 4:10 PM on Monday 12 October":
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