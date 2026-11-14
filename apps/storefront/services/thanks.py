"""
The end-of-day thank-you (14 Nov 2026).

It replaces the welcome that staff registration used to send. "Welcome to
Farhat Printing Press!" arrived while the customer was still standing at
the counter, mid-job, and read like an advert. A thank-you once they've
been served says the same thing at the right moment.

Half an hour before each branch closes, by its own hours, everyone it
served today with nothing left unpaid hears from us once. First-timers get
a warmer message; returning customers a shorter one.

WhatsApp only, never SMS: inside the 24-hour window it costs nothing, and
an SMS thank-you is money spent on courtesy. So nobody is thanked who
hasn't written to us in the last day, or was thanked in the last week, or
asked us to stop messaging. Anyone mid-conversation is left until the
next run, five minutes later.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

KIND = 'thanks'
BEFORE_CLOSING = timedelta(minutes=30)
ONCE_IN = timedelta(days=7)
BUSY = timedelta(minutes=15)


def due(branch, now=None):
    """Within the last half hour before this branch closes today."""
    from apps.organization.services import hours

    now = timezone.localtime(now or timezone.now())
    if not hours.is_trading_day(branch, now.date()):
        return False
    closes = hours.closing_at(branch, now.date(), now.tzinfo)
    return closes - BEFORE_CLOSING <= now < closes


def thank_all(now=None):
    """Every trading branch that is due. Returns how many customers were thanked."""
    from apps.organization.models import Branch

    return sum(thank_branch(branch, now) for branch in Branch.objects.filter(is_trading=True)
               if due(branch, now))


def _live(jobs):
    from apps.jobs.models import Job
    return jobs.exclude(status__in=[Job.DRAFT, Job.CANCELLED, Job.VOIDED])


def served_today(branch, day):
    """
    Customers this branch served today with nothing left unpaid. A
    production job with its deposit paid counts as paid: the deposit is
    what was owed today.
    """
    from apps.customers.models import CustomerProfile
    from apps.jobs.models import Job

    jobs = _live(Job.objects.filter(branch=branch, created_at__date=day, customer__isnull=False))
    owing = jobs.filter(payment_state=Job.Payment.UNPAID).values('customer')
    return CustomerProfile.objects.filter(pk__in=jobs.values('customer')).exclude(pk__in=owing)


def thank_branch(branch, now=None):
    now = now or timezone.now()
    day = timezone.localdate(now)
    sent = 0
    for customer in served_today(branch, day):
        try:
            sent += bool(thank(customer, day, now))
        except Exception:
            logger.exception('Thank-you not sent to customer %s', customer.pk)
    return sent


def thank(customer, day, now):
    """One customer, if every rule above allows. Returns the queued message, or None."""
    from apps.communications.models import Message
    from apps.communications.services.whatsapp_outbound import WindowClosed, send_text, thread_for
    from apps.communications.services.window import window_open

    conversation = thread_for(customer.phone)
    if conversation is None or conversation.marketing_opt_out or not window_open(conversation):
        return None
    said = conversation.messages.filter(is_internal_note=False)
    if said.filter(kind=KIND, created_at__gte=now - ONCE_IN).exclude(status=Message.FAILED).exists():
        return None
    if said.filter(created_at__gte=now - BUSY).exists():
        return None
    try:
        return send_text(conversation, thanks_text(customer, day), kind=KIND)
    except (WindowClosed, ValueError):
        return None


def thanks_text(customer, day):
    from apps.jobs.models import Job
    from apps.storefront.services.welcome import business_name, first_name

    name = first_name(customer)
    returning = _live(Job.objects.filter(customer=customer, created_at__date__lt=day)).exists()
    if returning:
        hello = f'Thank you for coming back today, {name}!' if name else 'Thank you for coming back today!'
        return f'{hello} We really appreciate you choosing {business_name()} \U0001F64F'
    hello = (f'Thank you for choosing {business_name()} today, {name}!' if name
             else f'Thank you for choosing {business_name()} today!')
    return (f'{hello} It was a pleasure serving you. '
            'Whenever you need anything printed, just message us here \U0001F60A')
