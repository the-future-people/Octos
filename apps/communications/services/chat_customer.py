"""
The customer behind a WhatsApp chat, for a job made at the counter (Layer 2, Step 2.4b, 11 Nov 2026).

Every job whose files came in on WhatsApp carries who it is for, even when they
never registered: the chat's own customer if it has one, else an existing
record with the same number (phone or secondary phone), else a light record
made from the chat (its WhatsApp name and number). A chat with a username and
no number has no number to make a record from; the job is still linked to it.
"""
from django.db import transaction
from django.db.models import Q


def _digits(phone):
    return ''.join(c for c in (phone or '') if c.isdigit())


def _forms(phone):
    """Every way the shop might have stored this number."""
    d = _digits(phone)
    if len(d) < 9:
        return []
    tail = d[-9:]
    return [f'+233{tail}', f'233{tail}', f'0{tail}']


def _stored_form(phone):
    """The number written the way existing customers' numbers are written."""
    from apps.customers.models import CustomerProfile
    tail = _digits(phone)[-9:]
    international = CustomerProfile.objects.filter(phone__startswith='+').exists()
    return f'+233{tail}' if international else f'0{tail}'


def customer_for_chat(conversation):
    """(customer, created) for this chat, or (None, False) when it has no number."""
    from apps.customers.models import CustomerProfile
    if conversation.customer_id:
        return conversation.customer, False
    forms = _forms(conversation.contact_phone)
    if not forms:
        return None, False
    with transaction.atomic():
        customer = (CustomerProfile.objects
                    .filter(Q(phone__in=forms) | Q(secondary_phone__in=forms)).first())
        created = customer is None
        if created:
            name = (conversation.contact_name or '').strip().split()
            customer = CustomerProfile.objects.create(
                phone=_stored_form(conversation.contact_phone),
                first_name=(name[0] if name else '')[:100],
            )
        conversation.customer = customer
        conversation.save(update_fields=['customer'])
    return customer, created


def chat_label(conversation):
    """
    How a chat's person is named on a receipt or a screen: their WhatsApp name,
    with their number, or their @username when the number is hidden.
    """
    name = (conversation.contact_name or '').strip()
    username = (getattr(conversation, 'contact_username', '') or '').strip()
    if conversation.contact_phone:
        return f'{name or "WhatsApp customer"} (WhatsApp)'
    handle = f'@{username}' if username else 'number hidden'
    return f'{name or handle} (WhatsApp {handle})' if name else f'{handle} (WhatsApp)'


def chat_identity(job):
    """
    (name, phone) for a job with no customer record, from the WhatsApp chat it
    is linked to, or None when it has no chat (11 Nov 2026). So a receipt for a
    WhatsApp customer is never just "Walk-in Customer": it can always be
    matched back to the person and their chat.
    """
    from apps.communications.models import Conversation
    if job is None or getattr(job, 'pk', None) is None:
        return None
    conversation = Conversation.objects.filter(jobs=job).order_by('-pk').first()
    if conversation is None:
        return None
    return chat_label(conversation), conversation.contact_phone or ''
