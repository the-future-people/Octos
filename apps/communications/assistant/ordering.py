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

One open order per chat (20 Nov 2026): Kings Hub changed his mind three
times and ended up with ORD-115 to 118, and two payment reminders. Each
prepare still makes a fresh order (its files and prices are this one's),
but the chat's earlier orders that no link was sent for are set aside
(abandoned, swept with their files). One whose link went out can't be:
money may be on its way. Octos is told, so the customer hears to use only
the new link, and only the newest is ever reminded (payment_reminder.py).
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
            if verdict['verdict'] == 'warn' and not _worth_a_warning(verdict, service, message):
                verdict = {**verdict, 'verdict': 'fine'}
            if verdict['verdict'] == 'warn' and not accept_warnings:
                staged_for_line.append(staged)
                return stop({'needs_customer_ok': True, 'file': name, 'checks': verdict['checks']})
            if counts_pages(service) and not specs.get('pages'):
                specs['pages'] = staged.page_count or 1   # the document's pages: the price halves them for both sides
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
        replaced, links_out = _set_aside_earlier(conversation, order)

    from apps.communications.assistant.tools import _about, _branch_name, _when
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
        'ready': _about(ready, now) if ready else None,
        'ready_note': None if ready else 'The team will confirm the ready time.',
        'next': 'Confirm this with the customer. Send the payment link only when they agree.',
        **({'replaces': replaced} if replaced else {}),
        **({'earlier_link_still_open': links_out,
            'tell_them': ('This replaces the earlier order. When you send the new link, tell them to '
                          'use only the new one and ignore the earlier link.')} if links_out else {}),
    }


BIG_OR_PHOTO = ('photo', 'poster', 'banner', 'flex', 'sticker', 'canvas', 'roll up', 'rollup', 'a3', 'a2',
                'a1', 'a0', 'large', 'billboard', 'backdrop')


def _worth_a_warning(verdict, service, message):
    """
    "It will print softer" matters for a photo or a big print, not for a
    letter on A4 (20 Nov 2026: a one-page MTN SIM request letter opened
    with "Your file will print a bit softer than usual"). A warning that is
    only about resolution, on a document printed at document sizes, is let
    through as fine. Anything else the checks warn about still stands.
    """
    checks = [c if isinstance(c, dict) else {'verdict': 'warn', 'message': str(c)} for c in verdict.get('checks') or []]
    warned = [c for c in checks if c.get('verdict') == 'warn']
    if not warned or any(c.get('name') != 'resolution' for c in warned):
        return True
    if (message.media_mime or '').startswith('image/'):
        return True
    if service.unit in ('PER_SQFT', 'PER_SQCM'):
        return True
    words = f'{service.name} {service.display_name or ""} {service.code}'.lower()
    return any(w in words for w in BIG_OR_PHOTO)


def chat_orders(conversation):
    """The orders Octos took in this chat, newest first."""
    from apps.storefront.models import OnlineOrder
    return (OnlineOrder.objects.filter(notes__contains=f'(conversation {conversation.pk})')
            .order_by('-created_at', '-pk'))


def _set_aside_earlier(conversation, order):
    """
    ([order numbers set aside], [order numbers whose link is still out]).
    Never touches an order with a link out, paid or made into a job.
    """
    from apps.storefront.models import OnlineOrder
    earlier = chat_orders(conversation).exclude(pk=order.pk).filter(paid_at__isnull=True, job__isnull=True)
    drafts = list(earlier.filter(status=OnlineOrder.Status.DRAFT).values_list('order_number', flat=True))
    if drafts:
        earlier.filter(order_number__in=drafts).update(
            status=OnlineOrder.Status.ABANDONED, expires_at=timezone.now())
    links = list(earlier.filter(status=OnlineOrder.Status.AWAITING_PAYMENT).values_list('order_number', flat=True))
    return drafts, links


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


def pay_at_counter(conversation, order_number, now=None):
    """
    The customer would rather pay when they collect (24 Nov 2026): the
    order goes to the front desk with a pickup code. Printed ahead for a
    customer we know and a small job, otherwise when they arrive.
    """
    from django.utils import timezone
    from apps.communications.assistant.tools import _about
    from apps.jobs.services.counter_orders import CounterRefused, reserve
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.accounts import find_lead

    now = now or timezone.now()
    lead = find_lead(conversation.contact_phone)
    order = OnlineOrder.objects.filter(order_number=order_number, lead=lead).first() if lead else None
    if order is None:
        return {'success': False, 'error': 'No order with that number for this customer.'}
    try:
        job = reserve(order, conversation, now)
    except CounterRefused as refused:
        if str(refused) == 'needs_deposit':
            return {'success': False, 'needs_deposit': True,
                    'say': ("Part of this order is made on the production floor, and that starts only once at "
                            "least 70% is paid. Tell them kindly: they can pay through the link, or come in and "
                            "pay at the counter, and we start as soon as it's paid.")}
        return {'success': False, 'error': str(refused)}
    total = f'GHS {job.estimated_cost:,.2f}'
    if job.print_ahead:
        ready = _about(job.estimated_ready_at, now) if job.estimated_ready_at else None
        return {'success': True, 'code': job.counter_code, 'printed_ahead': True, 'ready': ready, 'total': total,
                'say': ("Tell them warmly it's no problem: we'll have it printed and ready"
                        + (f' {ready}' if ready else '') + ", they pay when they collect, and give them their "
                        "code to show at the counter. Don't offer the link again.")}
    return {'success': True, 'code': job.counter_code, 'printed_ahead': False, 'total': total,
            'say': ("Tell them warmly it's no problem: their order is prepared and we'll print it as soon as they "
                    "arrive; they just show this code at the counter and pay there. Don't offer the link again.")}


def _lead_for(conversation):
    """The customer's storefront account, found by any form of the number, or made now."""
    from apps.storefront.models import Lead
    from apps.storefront.services.accounts import find_lead, normalise_phone

    lead = find_lead(conversation.contact_phone)
    if lead is not None:
        return lead
    from apps.communications.services.names import first_name_from
    first = (first_name_from(conversation.contact_name) or 'Customer')[:100]
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