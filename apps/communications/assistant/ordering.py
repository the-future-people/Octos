"""
Octos taking an order on WhatsApp, on the storefront's own foundations.

prepare_order builds the order as agreed in the chat: each line's file
(sent in this conversation, already kept) judged against that line by
inspect_file, the pages a printing job is priced by taken from the file
(sheets_for, the storefront's rule), the whole order priced by
price_lines, an OnlineOrder for the customer's lead at a branch Octos
speaks for that can make every line, the files attached as artwork, and
the ready time from the promise engine (counted from opening at night).

send_payment_link starts payment through start_payment, the storefront
pay button's own path, only for this customer's order, and only after
they have agreed. From payment on, nothing is new: the webhook, the
conversion to a job and the customer's messages are the storefront's.

Each prepare makes a fresh order; earlier unpaid ones expire as any
unpaid storefront order does.
"""
import logging
import os
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.communications.models import Message

logger = logging.getLogger(__name__)


def prepare_order(conversation, lines, accept_warnings=False, branches=()):
    from apps.jobs.models import Service
    from apps.jobs.services.availability import can_make, counts_pages, sheets_for
    from apps.storefront.batch_commit import _attach_copies
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.conversion import promise_for
    from apps.storefront.services.inspection import inspect_file
    from apps.storefront.services.pricing import price_lines

    if not lines:
        return {'success': False, 'error': 'Nothing to order yet.'}

    raw, staged_for_line, services = [], [], []

    def stop(result):
        _discard(staged_for_line)
        return {'success': False, **result}

    for number, line in enumerate(lines, 1):
        service = Service.objects.filter(code=line.get('service_code'), is_active=True).first()
        if service is None:
            return stop({'error': f"Line {number}: no active service with code {line.get('service_code')!r}."})
        services.append(service)
        from apps.communications.assistant.tools import whatsapp_specs
        specs = whatsapp_specs(service, line.get('specifications'))
        quantity = max(1, int(line.get('quantity') or 1))

        codes = list(line.get('addon_codes') or [])
        found_addons = dict(Service.objects.filter(code__in=codes, is_active=True).values_list('code', 'pk'))
        missing = [c for c in codes if c not in found_addons]
        if missing:
            return stop({'error': f"Line {number}: not offered: {', '.join(missing)}."})

        staged = None
        if line.get('file'):
            message = conversation.messages.filter(pk=line.get('file'), direction=Message.INBOUND).first()
            if message is None:
                return stop({'error': f'Line {number}: that file is not one this customer sent here.'})
            if not message.media_file:
                return stop({'error': f'Line {number}: the file is still being saved. Try again in a moment.'})
            with message.media_file.open('rb') as handle:
                content = handle.read()
            name = message.media_name or os.path.basename(message.media_file.name)
            _, _, verdict, staged = inspect_file(content, name, message.media_mime, specs)
            if verdict['verdict'] == 'refuse':
                return stop({'file_refused': True, 'file': name, 'checks': verdict['checks']})
            if verdict['verdict'] == 'warn' and not accept_warnings:
                staged_for_line.append(staged)
                return stop({'needs_customer_ok': True, 'file': name, 'checks': verdict['checks']})
            if counts_pages(service) and not specs.get('pages'):
                specs['pages'] = sheets_for(service, staged.page_count)
        elif service.requires_file_upload:
            return stop({'error': f"Line {number}: {service.display_name or service.name} needs the customer's file."})

        staged_for_line.append(staged)
        raw.append({'service': service.pk, 'quantity': quantity, 'specifications': specs,
                    'addons': list(found_addons.values())})

    branch = next((b for b in branches if all(can_make(s, b) for s in services)), None)
    if branch is None:
        return stop({'error': 'None of the branches I speak for can make all of this.'})

    priced, total, problem = price_lines(raw)
    if problem:
        return stop({'error': problem})

    lead = _lead_for(conversation)
    with transaction.atomic():
        order = OnlineOrder.objects.create(
            lead=lead, branch=branch, line_items=priced, full_total=total, total=total,
            notes=f'Taken by Octos on WhatsApp (conversation {conversation.pk}).',
        )
        order.touch_expiry()
        order.save(update_fields=['expires_at'])
        for line, staged in zip(priced, staged_for_line):
            if staged is not None:
                _attach_copies(order, [line['id']], staged)

    from apps.communications.assistant.tools import _branch_name, _when
    from apps.production.models import ServiceStation
    # A service with no route on the floor has no measured work, so the
    # engine would promise "ready at opening" for it. Octos never guesses.
    routed = set(ServiceStation.objects.filter(service__in=services).values_list('service_id', flat=True))
    ready = promise_for(order) if all(s.pk in routed for s in services) else None
    now = timezone.localtime()
    return {
        'success': True,
        'order': order.order_number,
        'branch': _branch_name(branch),
        'lines': [{
            'what': line['service_name'],
            'quantity': line['quantity'],
            'unit_price': f"GHS {Decimal(line['unit_price']):.2f}",
            'pages': line['specifications'].get('pages'),
            'total': f"GHS {Decimal(line['total']):.2f}",
        } for line in priced],
        'total': f'GHS {total:.2f}',
        'ready': _when(ready, now) if ready else None,
        'ready_note': None if ready else 'The team will confirm the ready time.',
        'next': 'Confirm this with the customer. Send the payment link only when they agree.',
    }


def send_payment_link(conversation, order_number):
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.accounts import find_lead
    from apps.storefront.services.payment import PaymentRefused, start_payment

    lead = find_lead(conversation.contact_phone)
    order = OnlineOrder.objects.filter(order_number=order_number, lead=lead).first() if lead else None
    if order is None:
        return {'success': False, 'error': "No order with that number for this customer."}
    try:
        started = start_payment(order)
    except PaymentRefused as refused:
        return {'success': False, 'error': refused.detail}
    return {'success': True, 'link': started['authorization_url'], 'amount': f"GHS {started['amount']}"}


def _lead_for(conversation):
    """The customer's storefront account, found by any form of the number, or made now."""
    from apps.storefront.models import Lead
    from apps.storefront.services.accounts import find_lead, normalise_phone

    lead = find_lead(conversation.contact_phone)
    if lead is not None:
        return lead
    first = ((conversation.contact_name or '').strip().split() or ['Customer'])[0][:100]
    return Lead.objects.create(phone=normalise_phone(conversation.contact_phone), first_name=first)


def _discard(staged_uploads):
    """Files staged for an order that won't be made are removed, never left behind."""
    for staged in staged_uploads:
        if staged is None:
            continue
        try:
            staged.file.delete(save=False)
            staged.delete()
        except Exception:
            logger.warning('Could not discard staged upload %s', staged.pk, exc_info=True)