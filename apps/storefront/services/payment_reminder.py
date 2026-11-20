"""
One reminder for an order Octos took on WhatsApp that hasn't been paid
for (14 Nov 2026).

Octos prices a job in the chat, sends the payment link, and often hears
nothing back: the customer got busy, or the link got buried. Two hours
later, while the branch is open, Octos asks once whether they still want
it. If they say yes, Octos sends the link again. The reminder never
carries a link itself: an old link is easy to ignore, a question isn't.

Once per order, ever, and once per chat (20 Nov 2026): when a customer
changed their order and a link went out for each, only the newest order
is asked about, and never twice in a day. Not sent once the order is paid or cancelled, when
the customer already said no after the link, or mid-conversation (the
next run catches it). "I'll pay tomorrow" isn't a no, so it still gets
the reminder. WhatsApp only, inside the 24-hour window; never SMS.
"""
import logging
import re
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

KIND = 'payment_reminder'
AFTER = timedelta(hours=2)
TOO_OLD = timedelta(days=2)
BUSY = timedelta(minutes=15)
TAKEN_ON_WHATSAPP = 'Taken by Octos on WhatsApp'
CONVERSATION = re.compile(r'\(conversation (\d+)\)')
SAID_NO = re.compile(
    r"^\W*(no|nope|no thanks?|no thank you)\W*$"
    r"|\bcancel|\bnot interested\b|\bdon['’]?t want\b|\bno longer (need|want)\b"
    r"|\bchanged my mind\b|\bforget (it|about it)\b",
    re.IGNORECASE,
)


def due_orders(now):
    """
    Waiting for payment, the link sent between two hours and two days ago,
    never reminded. updated_at is when the link went out: start_payment is
    the last thing to save the order before the money arrives.
    """
    from apps.storefront.models import OnlineOrder

    return (OnlineOrder.objects.select_related('lead', 'branch')
            .filter(status=OnlineOrder.Status.AWAITING_PAYMENT, paid_at__isnull=True,
                    payment_reminded_at__isnull=True, notes__contains=TAKEN_ON_WHATSAPP,
                    updated_at__lte=now - AFTER, updated_at__gte=now - TOO_OLD))


def remind_all(now=None):
    now = now or timezone.now()
    sent = 0
    for order in due_orders(now):
        try:
            sent += bool(remind(order, now))
        except Exception:
            logger.exception('Payment reminder not sent for %s', order.order_number)
    return sent


def remind(order, now):
    """One order, if every rule above allows. Returns the queued message, or None."""
    from apps.communications.models import Message
    from apps.communications.services.whatsapp_outbound import WindowClosed, send_text
    from apps.communications.services.window import window_open
    from apps.organization.services import hours
    from apps.storefront.models import OnlineOrder

    if order.branch_id and not hours.is_open(order.branch, now):
        return None                      # tried again when the doors open
    conversation = _thread(order)
    if conversation is None or not window_open(conversation):
        return None
    # One reminder per chat: a newer order from it, or a reminder to it today, settles this one.
    newer = (OnlineOrder.objects.filter(notes__contains=f'(conversation {conversation.pk})',
                                        created_at__gt=order.created_at)
             .exclude(status=OnlineOrder.Status.ABANDONED).exists())
    reminded = conversation.messages.filter(kind=KIND, created_at__gte=now - timedelta(hours=20)).exists()
    if newer or reminded:
        OnlineOrder.objects.filter(pk=order.pk, payment_reminded_at__isnull=True).update(payment_reminded_at=now)
        return None
    said = conversation.messages.filter(is_internal_note=False)
    if said.filter(created_at__gte=now - BUSY).exists():
        return None
    since_link = said.filter(direction=Message.INBOUND, created_at__gte=order.updated_at)
    if any(SAID_NO.search(body or '') for body in since_link.values_list('body', flat=True)):
        return None
    # Claimed before sending, so two runs can never both send.
    claimed = OnlineOrder.objects.filter(pk=order.pk, payment_reminded_at__isnull=True).update(
        payment_reminded_at=now)
    if not claimed:
        return None
    try:
        return send_text(conversation, reminder_text(order), kind=KIND)
    except (WindowClosed, ValueError):
        return None


def _thread(order):
    """The chat the order was taken in, from its note; else the customer's thread."""
    from apps.communications.models import Conversation
    from apps.communications.services.whatsapp_outbound import thread_for

    found = CONVERSATION.search(order.notes or '')
    if found:
        conversation = (Conversation.objects.filter(pk=found.group(1))
                        .exclude(status=Conversation.SPAM).first())
        if conversation is not None:
            return conversation
    return thread_for(order.lead.phone) if order.lead_id else None


def reminder_text(order):
    from apps.communications.services.names import name_for

    lead_name = (order.lead.first_name or '') if order.lead_id else ''
    try:
        chat = _thread(order)
    except Exception:
        chat = None
    name = name_for(chat, fallback=lead_name)
    items = [line.get('service_name') for line in (order.line_items or []) if line.get('service_name')]
    if len(items) == 1:
        what = f'order for {items[0]}'
    elif items:
        what = f'order for {items[0]} and {len(items) - 1} more'
    else:
        what = 'order'
    hello = f'Hi {name}, your' if name else 'Hi, your'
    return (f'{hello} {what} (GHS {order.total:.2f}) is still waiting for payment. '
            "Would you still like it? Just say yes and I'll send the link.")
