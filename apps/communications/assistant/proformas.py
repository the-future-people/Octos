"""
Octos issues proformas (7 Nov 2026, decided with Khofi).

A customer asks for a quotation "for my office" or "for the school". Octos
gathers the lines as it would for an order, then issues a proforma through
the same engine a Branch Manager uses, as its own account (issued by
Octos, so its quotes are always told apart), and sends the PDF here.

Proformas go to registered customers only (the engine's rule: converting
one needs a real record). So the customer is found by the chat's record or
the phone number; when there is none, Octos asks for the least a proforma
needs (a person's first and last name, or a business's name and a contact
person), registers them and links them to the chat.
"""
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

OCTOS_ROLE = 'OCTOS'


def octos_user():
    """The account Octos issues as (manage.py setup_octos), or None."""
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(role__name=OCTOS_ROLE).first()


def find_customer(conversation):
    """The chat's customer record, else one with this phone number, else None."""
    from apps.customers.models import CustomerProfile
    if getattr(conversation, 'customer_id', None):
        return conversation.customer
    phone = conversation.contact_phone or ''
    try:
        from apps.core.phones import lookup_forms
        forms = list(lookup_forms(phone)) or [phone]
    except Exception:
        forms = [phone]
    return CustomerProfile.objects.filter(phone__in=forms).first()


def _register(conversation, details):
    """A customer record from the least a proforma needs, linked to the chat; None if too little."""
    from apps.customers.models import CustomerProfile
    first = (details.get('first_name') or '').strip()
    last = (details.get('last_name') or '').strip()
    company = (details.get('company_name') or '').strip()
    contact = (details.get('contact_person') or '').strip()
    if company and contact:
        bits = contact.split()
        customer = CustomerProfile.objects.create(
            phone=conversation.contact_phone, customer_type=CustomerProfile.BUSINESS, company_name=company,
            first_name=bits[0] if bits else '', last_name=' '.join(bits[1:]),
            notes='Registered by Octos on WhatsApp, for a proforma.')
    elif first and last:
        customer = CustomerProfile.objects.create(
            phone=conversation.contact_phone, customer_type=CustomerProfile.INDIVIDUAL,
            first_name=first, last_name=last,
            notes='Registered by Octos on WhatsApp, for a proforma.')
    else:
        return None
    type(conversation).objects.filter(pk=conversation.pk).update(customer=customer)
    conversation.customer = customer
    return customer


def _raw_lines(lines):
    """Octos's lines (service codes, specifications, add-on codes) as the engine's."""
    from apps.jobs.models import Service
    raw = []
    for number, line in enumerate(lines, start=1):
        service = Service.objects.filter(code=line.get('service_code'), is_active=True).first()
        if service is None:
            raise ValueError(f"Line {number}: no active service {line.get('service_code')!r}.")
        specs = dict(line.get('specifications') or {})
        addon_ids = []
        for code in line.get('addon_codes') or []:
            addon = service.addons.filter(code=code, is_active=True).first()
            if addon is None:
                raise ValueError(f'Line {number}: {code} is not offered with {service.name}.')
            addon_ids.append(addon.pk)
        raw.append({
            'service': service.pk,
            'quantity': int(line.get('quantity') or 1),
            'pages': int(specs.pop('pages', 1) or 1),
            'is_color': bool(specs.pop('is_color', False)),
            'width_in': specs.pop('width_in', None),
            'height_in': specs.pop('height_in', None),
            'ring_size': specs.pop('ring_size', None),
            'output_mode': specs.pop('output_mode', None),
            'specifications': specs,
            'addons': addon_ids,
        })
    return raw


def send_proforma(conversation, lines, customer_details=None):
    """
    Issue a proforma for these lines and send its PDF in this chat.
    Returns what happened, for Octos to tell the customer in its own words.
    """
    from apps.jobs.pdf.proforma_pdf import build_proforma_pdf
    from apps.jobs.services.proforma_engine import ProformaEngine
    from apps.organization.models import Branch
    from apps.communications.services import whatsapp_outbound

    if not lines:
        return {'error': 'No lines: gather what the customer wants first.'}
    actor = octos_user()
    if actor is None:
        return {'error': "Octos isn't set up to issue proformas yet (manage.py setup_octos). Hand this to a person."}
    branch = Branch.objects.filter(is_trading=True, is_active=True).first()
    if branch is None:
        return {'error': 'No branch is trading.'}

    customer = find_customer(conversation)
    details = customer_details or {}
    if customer is None:
        customer = _register(conversation, details)
        if customer is None:
            return {'needs_customer_details': True,
                    'ask_for': "the customer's first and last name, or for a business, its name and a contact person"}

    try:
        raw = _raw_lines(lines)
        engine = ProformaEngine(branch)
        proforma = engine.create(
            customer=customer, raw_lines=raw, actor=actor,
            contact_person=(details.get('contact_person') or '').strip(),
            contact_phone=conversation.contact_phone,
            notes='Issued by Octos on WhatsApp.')
        proforma = engine.issue(proforma, actor=actor)
    except (ValueError, PermissionError) as refused:
        return {'error': str(refused)}

    pdf = build_proforma_pdf(proforma)
    total = f'GHS {Decimal(proforma.total):.2f}'
    valid = proforma.valid_until.strftime('%-d %B %Y') if hasattr(proforma.valid_until, 'strftime') else str(proforma.valid_until)
    caption = f'Proforma {proforma.proforma_number}: {total}, valid until {valid}.'
    try:
        whatsapp_outbound.send_text(conversation, caption, document=pdf, filename=f'{proforma.proforma_number}.pdf')
        sent = True
    except Exception:
        logger.exception('Could not send proforma %s', proforma.proforma_number)
        sent = False

    return {
        'proforma': proforma.proforma_number,
        'issued_to': proforma.issued_to,
        'lines': [{'name': li['service_name'], 'quantity': li['quantity'],
                   'total': f"GHS {Decimal(li['total']):.2f}"} for li in proforma.line_items],
        'total': total,
        'valid_until': valid,
        'sent_here_as_pdf': sent,
    }
