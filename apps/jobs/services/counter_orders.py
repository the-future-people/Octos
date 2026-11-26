"""
Pays at the counter (24 Nov 2026).

Many customers send their file on WhatsApp and would rather pay when they
come: they want to see the print first, they pay cash, or they don't trust
links. Octos used to say "no problem" and leave it there, so nothing was
ready when they walked in and the attendant started from the chat.

Now Octos takes the order either way. Front-desk work only: anything for
the coordinator still needs its deposit before work starts.

  printed ahead      a customer we know (a customer record, or a chat at
                     least a month old), never a no-show, up to GHS 50.
                     The attendant prints it like any front-desk job.
  print on arrival   everyone else: the file is checked and the price set,
                     and it's printed when they come.

Either way they get a pickup code, never given twice. They come, the
attendant (or the counter QR) marks them here, and Send to cashier makes
it an ordinary counter sale: PENDING_PAYMENT, then the cashier.

Not collected by close of the day it was meant for, it goes to the
Waiting for collection shelf. A week on the shelf and Octos cancels it,
deletes the file and records the no-show, which ends printing ahead for
that customer (Khofi: Octos cancels it, not an employee).
"""
import logging
import secrets
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

PRINT_AHEAD_UP_TO = Decimal('50.00')
KNOWN_AFTER = timedelta(days=30)
SHELF_DAYS = 7


class CounterRefused(Exception):
    """Can't be taken as pay-at-the-counter, in words Octos or the attendant can say."""


# ── The code ─────────────────────────────────────────────────────────────────

def new_code():
    """
    A pickup code nobody has ever had: four digits while they last, then
    five, then six. The database refuses a repeat too (unique), so two
    orders at the same moment can't share one either; reserve() retries.
    """
    from apps.jobs.models import Job

    for digits in (4, 5, 6):
        for _ in range(40):
            code = f'{secrets.randbelow(10 ** digits):0{digits}d}'
            if not Job.objects.filter(counter_code=code).exists():
                return code
    raise RuntimeError('No free pickup code.')


# ── Who is printed ahead ─────────────────────────────────────────────────────

def known_customer(order, conversation=None, now=None):
    """
    The customer record this order's number already has (before this order
    made one), or None. Known means a record, which anyone who has paid us
    has, or a chat with us at least a month old.
    """
    from apps.storefront.services.conversion import _customer_for

    lead = order.lead if order.lead_id else None
    existing = None
    if lead is not None:
        from apps.customers.models import CustomerProfile
        from apps.core.phones import lookup_forms
        existing = lead.customer if lead.customer_id else (
            CustomerProfile.objects
            .filter(Q(phone__in=lookup_forms(lead.phone)) | Q(secondary_phone__in=lookup_forms(lead.phone)))
            .order_by('created_at').first())
    if existing is not None:
        return existing, True
    now = now or timezone.now()
    old_chat = conversation is not None and conversation.created_at <= now - KNOWN_AFTER
    return (_customer_for(order) if lead is not None else None), old_chat


def may_print_ahead(total, customer, known):
    """Known, never failed to come, and small enough to risk the paper."""
    from apps.jobs.models import Job

    if not known or total > PRINT_AHEAD_UP_TO:
        return False
    if customer is not None and Job.objects.filter(customer=customer, no_show=True).exists():
        return False
    return True


# ── Taking it ────────────────────────────────────────────────────────────────

def reserve(order, conversation=None, now=None):
    """
    The order becomes a job at the front desk that pays at the counter.
    Returns the job; the same job again if it was already reserved.
    Raises CounterRefused when it can't be.
    """
    from apps.jobs.models import Job
    from apps.jobs.services.front_desk import _tell_branch, is_front_desk_work
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.conversion import _carry_artwork, _carry_lines, _title

    now = now or timezone.now()
    if order.status == OnlineOrder.Status.COUNTER:
        job = Job.objects.filter(notes__contains=f'({order.order_number})', counter_code__isnull=False).first()
        if job is not None:
            return job
    if order.is_paid or order.status in (OnlineOrder.Status.PAID, OnlineOrder.Status.CONVERTED):
        raise CounterRefused('This order is already paid for.')
    # An order just prepared is still a DRAFT: no link was ever sent, the
    # customer went straight to "I'll pay when I come" (25 Nov 2026: this
    # refused every such order, and only ones sent a link first got through).
    if order.status not in (OnlineOrder.Status.DRAFT, OnlineOrder.Status.AWAITING_PAYMENT) or not order.line_items:
        raise CounterRefused('There is no agreed order to keep for the counter.')
    if order.status == OnlineOrder.Status.DRAFT and order.expires_at and order.expires_at <= now:
        raise CounterRefused('There is no agreed order to keep for the counter.')
    if not order.branch_id:
        raise CounterRefused('The order has no branch.')
    if not front_desk_order(order):
        raise CounterRefused('needs_deposit')

    customer, known = known_customer(order, conversation, now)
    total = sum((Decimal(str(line.get('total') or '0')) for line in order.line_items), Decimal('0'))
    ahead = may_print_ahead(total, customer, known)
    if ahead and order.promised_for is None:
        # The ready time is fixed when a link goes out; with no link, now.
        from apps.storefront.services.conversion import promise_for
        promised = promise_for(order)
        if promised is not None:
            OnlineOrder.objects.filter(pk=order.pk).update(promised_for=promised)
            order.promised_for = promised

    for attempt in range(5):
        try:
            with transaction.atomic():
                locked = OnlineOrder.objects.select_for_update().get(pk=order.pk)
                if locked.status == OnlineOrder.Status.COUNTER:
                    return reserve(locked, conversation, now)
                code = new_code()
                job = Job.objects.create(
                    branch=order.branch,
                    customer=customer,
                    job_type=Job.INSTANT,
                    title=_title(order),
                    status=Job.AWAITING_ARRIVAL,
                    estimated_cost=total,
                    intake_by=None,
                    intake_channel=Job.WHATSAPP,
                    payment_state=Job.Payment.UNPAID,
                    work_state='RECEIVED',
                    handover_state='AWAITING_COLLECTION',
                    deposit_percentage=100,
                    amount_paid=Decimal('0'),
                    estimated_ready_at=(order.promised_for if ahead else None),
                    notes=f'Pays at the counter, code {code}. Taken by Octos on WhatsApp ({order.order_number}).',
                    counter_code=code,
                    print_ahead=ahead,
                )
                _carry_lines(order, job)
                if not is_front_desk_work(job):
                    raise CounterRefused('needs_deposit')      # rolls the job back
                Job.objects.filter(pk=job.pk).update(front_desk=True)
                job.front_desk = True
                locked.status = OnlineOrder.Status.COUNTER
                locked.save(update_fields=['status', 'updated_at'])
                if conversation is not None:
                    conversation.jobs.add(job)
                _tell_branch(job)
            break
        except IntegrityError:
            if attempt == 4:
                raise
            continue                     # someone took that code a moment ago
    _carry_artwork(order, job)
    return job


def front_desk_order(order):
    """Every line and add-on on the order is instant work: the attendants do it, no deposit."""
    from apps.jobs.models import Service

    ids = []
    for line in order.line_items or []:
        ids.append(line.get('service'))
        ids += [extra.get('service') for extra in line.get('addons') or []]
    if not ids or None in ids:
        return False
    categories = set(Service.objects.filter(pk__in=ids).values_list('category', flat=True))
    return categories == {Service.INSTANT}


# ── At the counter ───────────────────────────────────────────────────────────

def waiting(branch=None):
    from apps.jobs.models import Job
    jobs = Job.objects.filter(status=Job.AWAITING_ARRIVAL, counter_code__isnull=False)
    return jobs.filter(branch=branch) if branch is not None else jobs


def waiting_for(customer_id, branch=None):
    """
    Their orders waiting at the counter (26 Nov 2026): staff made a second
    job for Fiifi's files while his pickup code 5039 was still waiting.
    The customer on the job, or on a chat the job is linked to.
    """
    from django.db.models import Q
    return (waiting(branch).filter(Q(customer_id=customer_id) | Q(conversations__customer_id=customer_id))
            .distinct().order_by('created_at'))


def replace(job, actor):
    """A new job made at the counter takes its place: cancelled, saying why and by whom."""
    from apps.jobs.models import Job
    from apps.jobs.status_engine import JobStatusEngine
    if job.status != Job.AWAITING_ARRIVAL or not job.counter_code:
        raise CounterRefused(f'{job.job_number} is not waiting at the counter.')
    who = (getattr(actor, 'full_name', '') or getattr(actor, 'email', '') or 'staff').strip()
    with transaction.atomic():
        JobStatusEngine.advance(job=job, to_status=Job.CANCELLED, actor=actor,
                                notes=f'Code {job.counter_code}: replaced by a new job made at the counter by {who}.')
    return job


def here(job, now=None):
    """They came: off the shelf if it was there, and on the attendant's screen as here now."""
    from apps.jobs.models import Job
    from apps.jobs.services.front_desk import _tell_branch

    if job.status != Job.AWAITING_ARRIVAL:
        raise CounterRefused(f'{job.job_number} is not waiting for the customer.')
    job.arrived_at = job.arrived_at or (now or timezone.now())
    job.shelved_at = None
    job.save(update_fields=['arrived_at', 'shelved_at', 'updated_at'])
    _tell_branch(job)
    return job


def here_by_chat(conversation, branch=None, now=None):
    """The counter QR or "I'm at the counter": their waiting orders, marked here. Returns them."""
    from apps.jobs.models import Job
    jobs = [j for j in waiting(branch).filter(conversations=conversation)
            .filter(Q(shelved_at__isnull=True) | Q(shelved_at__gte=(now or timezone.now()) - timedelta(days=SHELF_DAYS)))
            .order_by('created_at')]
    for job in jobs:
        try:
            here(job, now)
        except Exception:
            logger.exception('Could not mark %s here', job.pk)
    return [Job.objects.get(pk=j.pk) for j in jobs]


def send_to_cashier(job, actor):
    """
    An ordinary counter sale from here on: today's sheet, PENDING_PAYMENT,
    the cashier's queue. Any attendant may do it, as at the counter.
    """
    from apps.finance.sheet_engine import SheetEngine
    from apps.jobs.models import Job
    from apps.jobs.services.front_desk import _tell_branch, may_take
    from apps.jobs.status_engine import JobStatusEngine

    if not may_take(actor):
        raise PermissionError('Only an attendant can send a job to the cashier.')
    if job.status != Job.AWAITING_ARRIVAL:
        raise CounterRefused(f'{job.job_number} is already with the cashier or closed.')
    sheet, _ = SheetEngine(job.branch).get_or_open_today()
    if not sheet:
        raise CounterRefused('There is no open sheet for today.')
    with transaction.atomic():
        JobStatusEngine.advance(job=job, to_status=Job.PENDING_PAYMENT, actor=actor,
                                notes=f'Pays at the counter: code {job.counter_code}, sent to the cashier.')
        job.daily_sheet = sheet
        job.arrived_at = job.arrived_at or timezone.now()
        job.shelved_at = None
        job.save(update_fields=['daily_sheet', 'arrived_at', 'shelved_at', 'updated_at'])
        _tell_branch(job)
        from apps.core.broadcast import broadcast_invalidation
        branch_id = job.branch_id
        transaction.on_commit(lambda: broadcast_invalidation(branch_id, ['paymentQueue', 'cashierSummary']))
    return job


def shelf(branch, query=''):
    """Waiting for collection: shelved, newest first, found by code, name or number."""
    jobs = waiting(branch).filter(shelved_at__isnull=False).select_related('customer')
    query = (query or '').strip()
    if query:
        digits = ''.join(c for c in query if c.isdigit())
        match = (Q(counter_code=query) | Q(job_number__icontains=query)
                 | Q(customer__first_name__icontains=query) | Q(customer__last_name__icontains=query))
        if len(digits) >= 4:
            match |= Q(customer__phone__contains=digits[-9:])
        jobs = jobs.filter(match)
    return list(jobs.order_by('-shelved_at')[:50])


# ── Closing time and the week after ──────────────────────────────────────────

def due_on_shelf(job, now):
    """The first closing after it was taken: an order at 9pm waits for tomorrow's close."""
    from apps.organization.services import hours

    made = timezone.localtime(job.created_at)
    day = made.date()
    for _ in range(14):
        if hours.is_trading_day(job.branch, day):
            closes = hours.closing_at(job.branch, day, made.tzinfo)
            if closes > job.created_at:
                return now >= closes
        day += timedelta(days=1)
    return True


def tidy(now=None):
    """
    Every quarter of an hour: shelve what closing passed by, cancel what
    sat a week on the shelf. Returns (shelved, cancelled).
    """
    from apps.accounts.system import octos_user
    from apps.jobs.models import Job, JobFile
    from apps.jobs.status_engine import JobStatusEngine

    now = now or timezone.now()
    shelved = cancelled = 0
    for job in waiting().filter(shelved_at__isnull=True, arrived_at__isnull=True).select_related('branch'):
        try:
            if due_on_shelf(job, now):
                Job.objects.filter(pk=job.pk, shelved_at__isnull=True).update(shelved_at=now)
                shelved += 1
                from apps.jobs.services.front_desk import _tell_branch
                with transaction.atomic():
                    _tell_branch(job)
        except Exception:
            logger.exception('Could not shelve %s', job.pk)

    octos = octos_user()
    if octos is None:
        logger.error('Pay-at-counter jobs not cancelled: the Octos account is missing (setup_octos).')
        return shelved, cancelled
    for job in waiting().filter(shelved_at__lte=now - timedelta(days=SHELF_DAYS)):
        try:
            with transaction.atomic():
                JobStatusEngine.advance(job=job, to_status=Job.CANCELLED, actor=octos,
                                        notes=f'Not collected after {SHELF_DAYS} days on the shelf: cancelled by Octos.')
                Job.objects.filter(pk=job.pk).update(no_show=True)
            for f in JobFile.objects.filter(job=job):
                try:
                    f.file.delete(save=False)
                    f.delete()
                except Exception:
                    logger.warning('Could not delete file %s of %s', f.pk, job.job_number, exc_info=True)
            cancelled += 1
        except Exception:
            logger.exception('Could not cancel %s', job.pk)
    return shelved, cancelled


# ── Telling them ─────────────────────────────────────────────────────────────

def ready_text(job):
    from apps.communications.services import names
    name = names.name_for(None, job.customer) if job.customer_id else ''
    where = (job.branch.name or 'Farhat').replace(' Branch', '')
    hello = f'Good news, {name}!' if name else 'Good news!'
    return (f'{hello} Your order is printed and ready at {where} \U0001F60A '
            f'Pay when you collect: your code is {job.counter_code}.')


def tell_ready(job):
    """A printed-ahead order is done: on WhatsApp if their window is open, else SMS. Never raises."""
    if not (job.counter_code and job.print_ahead and job.customer_id and job.customer.phone):
        return None
    if job.arrived_at:
        return None                      # they're standing there
    try:
        from apps.communications.services.whatsapp_outbound import try_send_text
        from apps.storefront.services.sms import send_sms
        body = ready_text(job)
        return try_send_text(job.customer.phone, body, 'counter_ready') or send_sms(job.customer.phone, body, kind='counter_ready')
    except Exception:
        logger.exception('Could not tell %s it is ready', job.job_number)
        return None

