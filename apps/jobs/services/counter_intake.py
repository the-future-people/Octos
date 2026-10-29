"""
A production or design job taken at the counter, joining the line.

The counter sells two kinds of work. Instant work is made while the
customer waits and leaves with them. Production and design work goes to
the floor, and for that the counter job must become what an online
order already is: inspected by the coordinator, made against a promise,
followed in the app or by SMS, and collected with a PIN.

It joins at the first payment that reaches the minimum (70% of the
cost, or any amount on a credit account). From that moment:

- the promise is fixed on the job, from the floor as it is then, by the
  same prediction service that promises online customers;
- the coordinator's arrivals include it (inspection.arrival_queue reads
  the payment itself, so a job never waits on a promise to be seen);
- it gets a customer-facing order record, linked to the customer by
  phone, which is what the app, tracking, the ready message, the
  collection PIN and the board all run on;
- the customer is told, by push if their phone has the app, else SMS.

Nothing here runs twice: a job that already has its order record has
joined.
"""

import logging
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

FLOOR_WORK = ('PRODUCTION', 'DESIGN')
MINIMUM_SHARE = Decimal('0.70')


def minimum_due(job):
    """What must be paid before the work starts: 70% of the cost."""
    cost = job.estimated_cost or Decimal('0')
    return (cost * MINIMUM_SHARE).quantize(Decimal('0.01'))


def has_paid_enough(job):
    if job.payment_method == 'CREDIT':
        return True
    if not job.estimated_cost:
        return False
    return (job.amount_paid or Decimal('0')) >= minimum_due(job)


def _lines(job):
    """The job's own items, as the prediction service wants them."""
    lines = []
    for item in job.line_items.filter(parent__isnull=True).select_related('service'):
        if item.service_id is None:
            continue
        lines.append((item.service, int(getattr(item, 'quantity', 1) or 1), int(getattr(item, 'pages', 1) or 1)))
    return lines


def _promise(job):
    from apps.production.services.prediction_service import PredictionService
    lines = _lines(job)
    if not lines or job.branch_id is None:
        return None
    try:
        return PredictionService(job.branch).predict(lines).ready_at
    except Exception:
        logger.exception('Could not work out a promise for %s', job.job_number)
        return None


def _order_lines(job):
    """The job's items in the shape the app and the board read."""
    out = []
    children = {}
    for item in job.line_items.select_related('service').order_by('id'):
        if getattr(item, 'parent_id', None):
            children.setdefault(item.parent_id, []).append(item)
    for item in job.line_items.filter(parent__isnull=True).select_related('service').order_by('id'):
        service = item.service
        name = (getattr(service, 'display_name', '') or service.name) if service else 'Item'
        out.append({
            'service': service.pk if service else None,
            'service_name': name,
            'base_name': service.name if service else name,
            'quantity': int(getattr(item, 'quantity', 1) or 1),
            'specifications': getattr(item, 'specifications', None) or {},
            'total': str(getattr(item, 'line_total', '') or ''),
            'addons': [
                {'service_name': (c.service.name if c.service_id else ''),
                 'quantity': int(getattr(c, 'quantity', 1) or 1),
                 'total': str(getattr(c, 'line_total', '') or '')}
                for c in children.get(item.pk, [])
            ],
        })
    return out


def _lead_for(job):
    """The customer's lead, found or made by their phone number."""
    from apps.storefront.models import Lead
    from apps.storefront.services.accounts import normalise_phone

    customer = job.customer
    if customer is None or not getattr(customer, 'phone', ''):
        return None
    phone = normalise_phone(customer.phone)
    if phone is None:
        return None
    first = (getattr(customer, 'first_name', '') or (getattr(customer, 'full_name', '') or '').split(' ')[0]
             or 'Customer')
    # However this number was stored before (0244... or +233...), the same
    # person's lead is found, never a second one made.
    from apps.storefront.services.accounts import find_lead
    lead = find_lead(phone) or Lead.objects.create(phone=phone, first_name=first, customer=customer)
    if lead.customer_id is None:
        lead.customer = customer
        lead.save(update_fields=['customer'])
    return lead


def _when(at):
    if at is None:
        return None
    local = timezone.localtime(at)
    day = 'today' if local.date() == timezone.localdate() else local.strftime('%a')
    return f'{local.strftime("%-I:%M %p").lower()} {day}'


def join_the_line(job, actor=None):
    """
    Called after every counter payment. Does its work once, the first
    time a production or design job has paid enough.
    """
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.messages import counter_paid_text
    from apps.storefront.services.notify import tell

    if job.job_type not in FLOOR_WORK:
        return None
    if OnlineOrder.objects.filter(job=job).exists():
        return None
    if not has_paid_enough(job):
        return None

    now = timezone.now()
    promise = _promise(job)
    if promise is not None and job.estimated_ready_at is None:
        job.estimated_ready_at = promise
        job.save(update_fields=['estimated_ready_at', 'updated_at'])

    lead = _lead_for(job)
    order = OnlineOrder.objects.create(
        lead=lead,
        branch=job.branch,
        job=job,
        line_items=_order_lines(job),
        full_total=job.estimated_cost or 0,
        total=job.estimated_cost or 0,
        status=OnlineOrder.Status.CONVERTED,
        paid_at=now,
        promised_for=job.estimated_ready_at,
        # Marks it as the counter's, and ties it to the job's own number.
        payment_reference=f'COUNTER:{job.job_number}',
    )

    if lead is not None:
        balance = job.balance_due or Decimal('0')
        when = _when(job.estimated_ready_at)
        ready = f'Ready about {when}.' if when else 'We will tell you when it is ready.'
        owing = f' Balance GHS {balance:.2f} on collection.' if balance > 0 else ''
        tell(
            order, 'paid', 'Order received',
            f'{job.job_number}: we are on it. {ready}{owing}',
            sms_text=counter_paid_text(order, balance),
        )
    return order