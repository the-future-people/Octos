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

23 Nov 2026: five customers with a WhatsApp username and no number (Kay,
Mc James, Kweku, S.K. Doh, Sylvia) were served, sent their receipts, and
never thanked: the thank-you looked for a chat by phone number only. Now
it thanks chats: every chat a customer served today writes from, and every
chat a job made today was linked to, whether or not it has a number.

24 Nov 2026 (Khofi): someone served late hears from us about three hours
later, even after we've closed. Loretta paid at 7:29pm and Nene at 7:27pm,
after the last run, and were never thanked. Now each chat is thanked at
whichever is later: half an hour before closing, or three hours after
their last job. Runs go on until three and a half hours after closing.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

KIND = 'thanks'
BEFORE_CLOSING = timedelta(minutes=30)
ONCE_IN = timedelta(days=7)
BUSY = timedelta(minutes=15)
AFTER_SERVED = timedelta(hours=3)          # never sooner than this after their last job
LATE = timedelta(hours=3, minutes=30)      # runs go on this long after closing


def due(branch, now=None):
    """From half an hour before this branch closes today until three and a half hours after."""
    from apps.organization.services import hours

    now = timezone.localtime(now or timezone.now())
    if not hours.is_trading_day(branch, now.date()):
        return False
    closes = hours.closing_at(branch, now.date(), now.tzinfo)
    return closes - BEFORE_CLOSING <= now < closes + LATE


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


def chats_served_today(branch, day):
    """
    [(chat, customer or None, a job of theirs today)] for this branch today,
    one per chat: chats of customers served, then chats linked to a job made
    today with nothing on it unpaid, even with no number (a username chat).
    """
    from apps.communications.models import Conversation
    from apps.communications.services.whatsapp_outbound import thread_for
    from apps.jobs.models import Job

    found, seen, people = [], set(), set()

    def add(chat, customer, job):
        if chat is None or chat.pk in seen or chat.status == Conversation.SPAM:
            return
        if customer is not None and customer.pk in people:
            return                       # one thank-you a person, even with two chats
        seen.add(chat.pk)
        if customer is not None:
            people.add(customer.pk)
        found.append((chat, customer, job))

    today = _live(Job.objects.filter(branch=branch, created_at__date=day))
    owing = set(today.filter(payment_state=Job.Payment.UNPAID, customer__isnull=False)
                .values_list('customer', flat=True))
    for customer in served_today(branch, day):
        job = today.filter(customer=customer).order_by('-created_at').first()
        add(thread_for(customer.phone) or thread_for(customer.secondary_phone), customer, job)
    linked = (Conversation.objects
              .filter(channel=Conversation.WHATSAPP, branch__isnull=True, jobs__in=today)
              .distinct())
    for chat in linked:
        theirs = today.filter(conversations=chat)
        if theirs.filter(payment_state=Job.Payment.UNPAID).exists():
            continue
        job = theirs.order_by('-created_at').first()
        customer = chat.customer if chat.customer_id else (job.customer if job.customer_id else None)
        if customer is not None and customer.pk in owing:
            continue
        add(chat, customer, job)
    return found


def thank_branch(branch, now=None):
    now = now or timezone.now()
    day = timezone.localdate(now)
    sent = 0
    for chat, customer, job in chats_served_today(branch, day):
        if job is not None and now < job.created_at + AFTER_SERVED:
            continue                     # served late: their turn comes three hours on
        try:
            sent += bool(thank(chat, customer, day, now, job=job))
        except Exception:
            logger.exception('Thank-you not sent to chat %s', chat.pk)
    return sent


def thank(conversation, customer, day, now, job=None):
    """One chat, if every rule above allows. Returns the queued message, or None."""
    from apps.communications.models import Message
    from apps.communications.services.whatsapp_outbound import WindowClosed, send_text
    from apps.communications.services.window import window_open

    if conversation is None or conversation.marketing_opt_out or not window_open(conversation):
        return None
    said = conversation.messages.filter(is_internal_note=False)
    if said.filter(kind=KIND, created_at__gte=now - ONCE_IN).exclude(status=Message.FAILED).exists():
        return None
    if said.filter(created_at__gte=now - BUSY).exists():
        return None
    try:
        return send_text(conversation, thanks_text(customer, day, conversation=conversation, job=job),
                         kind=KIND)
    except (WindowClosed, ValueError):
        return None


def thanks_text(customer, day, conversation=None, job=None):
    from apps.communications.services import names
    from apps.jobs.models import Job
    from apps.storefront.services.welcome import business_name

    if customer is not None:
        name = names.name_for(conversation, customer)
        earlier = Job.objects.filter(customer=customer)
    else:
        name = names.for_job(job) if job is not None else names.name_for(conversation)
        earlier = Job.objects.filter(conversations=conversation) if conversation else Job.objects.none()
    returning = _live(earlier.filter(created_at__date__lt=day)).exists()
    if returning:
        hello = f'Thank you for coming back today, {name}!' if name else 'Thank you for coming back today!'
        return f'{hello} We really appreciate you choosing {business_name()} \U0001F64F'
    hello = (f'Thank you for choosing {business_name()} today, {name}!' if name
             else f'Thank you for choosing {business_name()} today!')
    return (f'{hello} It was a pleasure serving you. '
            'Whenever you need anything printed, just message us here \U0001F60A')
