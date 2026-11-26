"""
A quote from the inbox (25 Nov 2026, mock agreed with Khofi).

Staff build a quote beside the chat and send it without leaving it. It is
built on exactly what Octos uses when it takes an order, so nothing after
it is new:

  link      prepare_order, then send_payment_link: an order like Octos's,
            paid through the storefront's own Paystack path; paid, it
            becomes a job at the front desk or with the coordinator, and
            the customer gets the storefront's messages and receipt.
  counter   prepare_order, then pay_at_counter: a pickup code, printed
            ahead for a customer we know, otherwise on arrival (the same
            rule as Octos's, counter_orders.reserve).
  proforma  send_proforma: issued through the proforma engine by the
            Octos account, the PDF sent here by the person who asked.

Prices come only from the engine (price_lines), never typed. The preview
the panel shows while it is being built is priced the same way, so the
number staff see is the number the customer gets.

With "Attach the quote as a PDF" the order goes too, on paper
(jobs/pdf/quote_pdf.py). The quote message carries its order, so the chat
shows it as a card that follows the order: waiting, paid, at the counter.
"""
import logging
from decimal import Decimal

from django.utils import timezone

from apps.communications.models import Conversation, Message

logger = logging.getLogger(__name__)

HOW = ('link', 'counter', 'proforma')
KIND = 'quote'
PDF_KIND = 'quote_pdf'

WINDOW_CLOSED = ('Free replies are closed: the customer last wrote more than 24 hours ago. '
                 'Send an approved message first; once they reply you can send the quote.')
NEEDS_PHONE = ("This customer's number is hidden (a WhatsApp username). Ask for their phone number "
               "and save it on the chat first: the order and its receipt need one.")
NEEDS_DEPOSIT = ('Part of this is made on the production floor, which starts only once at least 70% is '
                 'paid. Send it with a payment link instead.')


def _branches():
    from apps.organization.models import Branch
    return list(Branch.objects.filter(is_trading=True, is_active=True))


def _money(value):
    return f'{Decimal(str(value or 0)):.2f}'


# ── What can be quoted ───────────────────────────────────────────────────────

def catalogue():
    """Every active service a trading branch can make, with what its price needs."""
    from apps.communications.assistant.tools import _service_facts
    from apps.jobs.models import Service
    from apps.jobs.services.availability import can_make, counts_pages

    found = []
    for service in Service.objects.filter(is_active=True).prefetch_related('addons').order_by('name'):
        if not can_make(service):
            continue
        facts = _service_facts(service)
        facts['counts_pages'] = bool(counts_pages(service))
        facts['display'] = (f'{service.display_name} · {service.variant_label}'
                            if service.display_name and service.variant_label
                            else (service.display_name or service.name))
        found.append(facts)
    return found


# ── The price while it's being built ─────────────────────────────────────────

def _raw_lines(conversation, lines):
    """
    The panel's lines (Octos's own shape: service_code, quantity,
    specifications, addon_codes, file) as price_lines takes them.
    Returns (raw, services, None) or (None, None, why not).
    """
    from apps.communications.assistant.tools import whatsapp_specs
    from apps.jobs.models import Service
    from apps.jobs.services.availability import counts_pages

    if not lines:
        return None, None, 'Add a line first.'
    raw, services = [], []
    for number, line in enumerate(lines, 1):
        service = Service.objects.filter(code=line.get('service_code'), is_active=True).first()
        if service is None:
            return None, None, f'Line {number}: pick a service.'
        specs = whatsapp_specs(service, line.get('specifications'))
        if counts_pages(service) and not specs.get('pages') and line.get('file'):
            sent = conversation.messages.filter(pk=line.get('file'), direction=Message.INBOUND).first()
            if sent is not None and sent.media_pages:
                specs['pages'] = sent.media_pages
        codes = list(line.get('addon_codes') or [])
        addons = dict(Service.objects.filter(code__in=codes, is_active=True).values_list('code', 'pk'))
        missing = [c for c in codes if c not in addons]
        if missing:
            return None, None, f"Line {number}: not offered: {', '.join(missing)}."
        services.append(service)
        raw.append({'service': service.pk, 'quantity': max(1, int(line.get('quantity') or 1)),
                    'specifications': specs, 'addons': list(addons.values())})
    return raw, services, None


def _lines_out(priced):
    """Priced lines as the panel, the card and the message show them."""
    out = []
    for line in priced or []:
        pages = (line.get('specifications') or {}).get('pages')
        out.append({
            'what': line.get('service_name'),
            'quantity': line.get('quantity'),
            'pages': pages,
            'price': _money(line.get('base_total') or line.get('total')),
            'addons': [{'what': a.get('service_name'), 'quantity': a.get('quantity'),
                        'detail': a.get('detail'), 'price': _money(a.get('total'))}
                       for a in line.get('addons') or []],
            'total': _money(line.get('total')),
        })
    return out


def preview(conversation, lines, now=None):
    """
    The quote as it stands: lines, total and ready time, priced as the
    order will be. Nothing is saved. {'error': ...} when it can't be priced
    yet (a missing size, a service no branch makes).
    """
    from apps.communications.assistant.tools import _about, _branch_name
    from apps.jobs.services.availability import can_make
    from apps.production.models import ServiceStation
    from apps.storefront.models import OnlineOrder
    from apps.storefront.services.conversion import promise_for
    from apps.storefront.services.pricing import price_lines

    raw, services, problem = _raw_lines(conversation, lines)
    if problem:
        return {'error': problem}
    branch = next((b for b in _branches() if all(can_make(s, b) for s in services)), None)
    if branch is None:
        return {'error': 'None of our branches can make all of this.'}
    priced, total, problem = price_lines(raw)
    if problem:
        return {'error': problem}

    ready = None
    routed = set(ServiceStation.objects.filter(service__in=services).values_list('service_id', flat=True))
    if all(s.pk in routed for s in services):
        moment = promise_for(OnlineOrder(branch=branch, line_items=priced))
        ready = _about(moment, now or timezone.now()) if moment else None
    return {'lines': _lines_out(priced), 'total': _money(total), 'ready': ready,
            'branch': _branch_name(branch)}


# ── Sending it ───────────────────────────────────────────────────────────────

def _line_text(line):
    bits = [line['what'] or 'Item']
    try:
        pages = int(line.get('pages') or 0)
    except (TypeError, ValueError):
        pages = 0
    if pages > 1:
        bits.append(f'{pages} pages')
    text = ', '.join(bits)
    rows = [f"• {text} × {line['quantity']}: GHS {line['price']}"]
    for extra in line['addons']:
        what = extra['what'] + (f" ({extra['detail']})" if extra.get('detail') else '')
        rows.append(f"• {what} × {extra['quantity']}: GHS {extra['price']}")
    return rows


def message_text(name, lines, total, how, ready=None, branch='', code='', printed_ahead=False, link=''):
    """What the customer reads: the quote, the total, and what happens next."""
    rows = [f"Here's your quote, {name} 😊" if name else "Here's your quote 😊", '']
    for line in lines:
        rows += _line_text(line)
    if how == 'counter':
        rows.append(f'*Total: GHS {total}*, you pay at the counter.')
        rows.append('')
        place = f' at {branch}' if branch else ''
        if printed_ahead:
            when = f' {ready}' if ready else ' for you'
            rows.append(f'Your pickup code is *{code}*. Show it{place} and it will be ready{when}.')
        else:
            rows.append(f"Your pickup code is *{code}*. We'll print it as soon as you arrive: "
                        f'just show the code{place} and pay there.')
    else:
        rows.append(f'*Total: GHS {total}*')
        rows.append('')
        rows.append("Pay here and we'll start right away."
                    + (f' It will be ready {ready}.' if ready else " We'll confirm when it will be ready."))
        rows.append(link)
    return '\n'.join(rows).strip()


def _why(prepared):
    """prepare_order's refusal, in words for the person sending."""
    if prepared.get('file_refused'):
        checks = '; '.join(c.get('message', '') if isinstance(c, dict) else str(c)
                           for c in prepared.get('checks') or [])
        return f"{prepared.get('file')} can't be printed as it is" + (f': {checks}' if checks else '.')
    return prepared.get('error') or 'This quote could not be made.'


def send(conversation, user, lines, how, pdf=True, customer=None, now=None):
    """
    Make the quote and send it here. Returns {'success': True, ...} with the
    messages sent, or {'error': ...} / {'needs_customer_details': True}.
    """
    from apps.communications.assistant import ordering, proformas
    from apps.communications.services import names, whatsapp_outbound
    from apps.communications.services.window import window_open
    from apps.storefront.models import OnlineOrder

    now = now or timezone.now()
    if how not in HOW:
        return {'error': 'Choose how to send it.'}
    if conversation.channel != Conversation.WHATSAPP:
        return {'error': 'Quotes are sent on WhatsApp.'}
    if not window_open(conversation):
        return {'error': WINDOW_CLOSED}

    if how == 'proforma':
        result = proformas.send_proforma(conversation, lines, customer or {}, sent_by=user)
        if not result.get('proforma'):
            return result
        if not result.get('sent_here_as_pdf'):
            return {'error': f"Proforma {result['proforma']} was made but couldn't be sent. "
                             'Find it in Proformas and send it again.'}
        _taken(conversation, user)
        return {'success': True, 'how': how, 'proforma': result['proforma'], 'total': result['total']}

    if not conversation.contact_phone:
        return {'error': NEEDS_PHONE}

    # Staff have seen the file and chosen to send: a file warning is theirs
    # to weigh, a refusal (nothing printable) still stops it.
    prepared = ordering.prepare_order(conversation, lines, accept_warnings=True, branches=_branches(),
                                      taken_by=user)
    if not prepared.get('success'):
        return {'error': _why(prepared)}
    order = OnlineOrder.objects.get(order_number=prepared['order'])
    lines_out = _lines_out(order.line_items)
    total = _money(order.total)
    name = names.name_for(conversation, fallback=conversation.contact_name)
    ready, code, ahead, link = prepared.get('ready'), '', False, ''

    if how == 'link':
        started = ordering.send_payment_link(conversation, order.order_number)
        if not started.get('success'):
            return {'error': started.get('error') or 'The payment link could not be made.'}
        link = started['link']
    else:
        counter = ordering.pay_at_counter(conversation, order.order_number, now=now)
        if not counter.get('success'):
            return {'error': NEEDS_DEPOSIT if counter.get('needs_deposit') else counter.get('error')}
        code, ahead = counter['code'], counter['printed_ahead']
        ready = counter.get('ready') if ahead else None

    sent = []
    try:
        if pdf:
            from apps.jobs.pdf.quote_pdf import build_quote_pdf
            whole = (conversation.customer.display_name if conversation.customer_id else '') or conversation.contact_name
            document = build_quote_pdf(order, name=whole or name, phone=conversation.contact_phone,
                                       ready=ready or '', code=code, how=how)
            paper = whatsapp_outbound.send_text(
                conversation, f'Quote {order.order_number}, GHS {total}', sent_by=user, kind=PDF_KIND,
                document=document, filename=f'Quote {order.order_number}.pdf')
            Message.objects.filter(pk=paper.pk).update(order=order)
            paper.refresh_from_db()           # send_text writes the file by update
            sent.append(paper)
        text = message_text(name, lines_out, total, how, ready=ready, branch=prepared.get('branch') or '',
                            code=code, printed_ahead=ahead, link=link)
        quote = whatsapp_outbound.send_text(conversation, text, sent_by=user, kind=KIND)
        Message.objects.filter(pk=quote.pk).update(order=order)
        quote.order = order
        sent.append(quote)
    except whatsapp_outbound.WindowClosed:
        return {'error': WINDOW_CLOSED}

    _taken(conversation, user)
    return {'success': True, 'how': how, 'order': order.order_number, 'total': total, 'code': code,
            'messages': sent}


def _taken(conversation, user):
    """A quote is a reply: the chat is theirs now, as after any reply (ConversationReplyView)."""
    from apps.communications.services import handover
    handover.staff_replied(conversation, user)
    if not conversation.assigned_to_id:
        type(conversation).objects.filter(pk=conversation.pk).update(assigned_to=user)
        conversation.assigned_to = user


# ── The card in the chat ─────────────────────────────────────────────────────

def card(message):
    """What the quote card shows for a quote message: its lines and where the order is now."""
    from apps.jobs.models import Job
    from apps.storefront.models import OnlineOrder

    order = message.order
    if order is None:
        return None
    S = OnlineOrder.Status
    job = None
    if order.status == S.COUNTER:
        job = (Job.objects.filter(notes__contains=f'({order.order_number})', counter_code__isnull=False)
               .only('job_number', 'status', 'payment_state', 'counter_code').first())
    total = _money(order.total)
    how = 'counter' if order.status == S.COUNTER else 'link'
    if order.paid_at or order.status in (S.PAID, S.CONVERTED):
        state, label = 'paid', f'Paid · GHS {total}'
    elif job is not None and job.payment_state == Job.Payment.SETTLED:
        state, label = 'paid', f'Paid at the counter · GHS {total}'
    elif job is not None and job.status == Job.CANCELLED:
        state, label = 'closed', 'Not collected, cancelled'
    elif order.status == S.COUNTER:
        state, label = 'counter', f'Pays at the counter · code {job.counter_code}' if job else 'Pays at the counter'
    elif order.status in (S.ABANDONED, S.CANCELLED):
        state, label = 'closed', 'Replaced by a newer quote' if order.status == S.ABANDONED else 'Cancelled'
    else:
        state, label = 'waiting', 'Waiting to pay'
    made = getattr(order, 'job', None) if order.status in (S.PAID, S.CONVERTED) else job
    return {
        'order': order.order_number,
        'lines': _lines_out(order.line_items),
        'total': total,
        'how': how,
        'state': state,
        'label': label,
        'code': job.counter_code if job else '',
        'ready_at': order.promised_for.isoformat() if order.promised_for else None,
        'job': getattr(made, 'job_number', None),
    }
