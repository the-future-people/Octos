"""
Collecting an online order at the counter.

The customer proves it is theirs with their phone number and a 4-digit
collection PIN, or by showing the QR in the app, which carries both. The
PIN is made when the order turns ready, sent in the ready SMS the
customer gets anyway and shown in their app, and shown nowhere in public:
the waiting-area board shows order numbers, never PINs.

Handing over goes through the status engine like every other move, so
the same permission checks apply, the move is logged with who and when,
and the customer's app is nudged to catch up.
"""

import secrets

from django.db import transaction


class CollectRefused(Exception):
    """Something the attendant can act on; the message says what."""


def ensure_pin(order):
    """The order's collection PIN, made once."""
    if not order.collection_pin:
        order.collection_pin = f'{secrets.randbelow(10000):04d}'
        order.save(update_fields=['collection_pin'])
    return order.collection_pin


def qr_payload(order):
    """What the app's QR carries: the order and its PIN, nothing else."""
    return f'PO:{order.order_number}:{order.collection_pin}'


def _ready(order):
    job = order.job
    return job is not None and job.work_state == 'DONE' and job.handover_state != 'HANDED_OVER'


def find(phone='', pin='', qr=''):
    """
    The ready orders this person may collect. A wrong PIN and a number
    with nothing ready give the same answer, so a guess learns nothing.
    """
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.accounts import find_lead, leads_for, normalise_phone

    if qr:
        parts = str(qr).strip().split(':')
        if len(parts) != 3 or parts[0] != 'PO':
            raise CollectRefused('That is not a Print Octos collection code.')
        _, number, pin = parts
        orders = OnlineOrder.objects.filter(order_number=number).select_related('job', 'lead', 'branch')
    else:
        number = normalise_phone(phone)
        if number is None:
            raise CollectRefused('Enter the customer’s phone number.')
        if not str(pin or '').strip():
            raise CollectRefused('Ask for their 4-digit collection PIN.')
        lead = find_lead(number)
        if lead is None:
            raise CollectRefused('Nothing ready for that number and PIN.')
        orders = (OnlineOrder.objects.filter(lead__in=leads_for(lead))
                  .select_related('job', 'lead', 'branch'))

    pin = str(pin or '').strip()
    found = [o for o in orders if _ready(o) and o.collection_pin and secrets.compare_digest(o.collection_pin, pin)]
    if not found:
        raise CollectRefused('Nothing ready for that number and PIN.')
    return found


def summary(order):
    """What the attendant hands over, line by line."""
    from apps.storefront.services.accounts import _detail
    job = order.job
    return {
        'order_number': order.order_number,
        'first_name': order.lead.first_name if order.lead_id else '',
        'branch': order.branch.name if order.branch_id else '',
        'total': f'{order.total:.2f}',
        'ready_since': job.updated_at.isoformat() if job else None,
        'lines': [{
            'name': line.get('service_name', ''),
            'detail': _detail(line),
            'addons': [
                {'name': a.get('service_name', ''), 'detail': a.get('detail', '')}
                for a in (line.get('addons') or [])
            ],
        } for line in (order.line_items or [])],
    }


@transaction.atomic
def hand_over(order_number, pin, actor, collected_by=''):
    """Release the order to whoever proved it; record who, by whom, when."""
    from apps.jobs.status_engine import JobStatusEngine
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.notify import tell

    order = (OnlineOrder.objects.select_for_update(of=('self',))
             .select_related('job', 'lead', 'branch').filter(order_number=order_number).first())
    if order is None or not order.collection_pin or not secrets.compare_digest(order.collection_pin, str(pin or '').strip()):
        raise CollectRefused('Nothing ready for that number and PIN.')
    job = order.job
    if job is None or job.work_state != 'DONE':
        raise CollectRefused('This order is not ready yet.')
    if job.handover_state == 'HANDED_OVER':
        raise CollectRefused('This order has already been collected.')

    who = (collected_by or '').strip()[:100]
    try:
        JobStatusEngine(job).move_handover(
            'HANDED_OVER', actor=actor,
            notes=f'Collected by {who}, for the customer' if who else 'Collected by the customer',
        )
    except PermissionError:
        raise CollectRefused('Your role cannot hand orders over.')
    except ValueError as err:
        raise CollectRefused(str(err) or 'This order cannot be handed over yet.')

    order.collected_by_name = who
    order.save(update_fields=['collected_by_name'])

    branch = order.branch.name if order.branch_id else 'the branch'
    tell(order, 'collected', 'Collected',
         f'{order.order_number} was collected at {branch}. Thank you for printing with us.')
    return order
