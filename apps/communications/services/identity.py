"""
Who a WhatsApp chat belongs to (9 Nov 2026), for customers with a WhatsApp
username whose number is hidden: their number, once they share it, finds
their customer record; with no record, their name starts one. Staff can link
a chat to a customer themselves too.
"""
import logging

from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)


def _set_phone(conversation, phone):
    """Give a chat its number, unless that number already has a chat of its own."""
    if not phone or conversation.contact_phone:
        return bool(conversation.contact_phone)
    try:
        with transaction.atomic():
            type(conversation).objects.filter(pk=conversation.pk).update(contact_phone=phone)
            conversation.contact_phone = phone
        return True
    except IntegrityError:
        logger.info('Phone %s already has its own chat; chat %s keeps its user id', phone, conversation.pk)
        return False


def link_customer(conversation, customer):
    """Link a chat to a customer record, and take the record's number if the chat has none."""
    from apps.core.phones import to_international
    type(conversation).objects.filter(pk=conversation.pk).update(customer=customer)
    conversation.customer = customer
    if customer.phone:
        _set_phone(conversation, to_international(customer.phone) or customer.phone)
    return customer


def match_phone(conversation, phone):
    """Save the number a customer shared; link their record if they have one. The record, or None."""
    from apps.core.phones import lookup_forms
    from apps.customers.models import CustomerProfile
    _set_phone(conversation, phone)
    customer = CustomerProfile.objects.filter(phone__in=lookup_forms(phone)).first()
    if customer is not None:
        link_customer(conversation, customer)
    return customer


def register_from_chat(conversation, first_name, last_name=''):
    """A customer record from the chat's number and the name they gave, linked to the chat."""
    from apps.customers.models import CustomerProfile
    if conversation.customer_id:
        return conversation.customer
    if not conversation.contact_phone:
        raise ValueError('The chat has no phone number yet.')
    customer = CustomerProfile.objects.filter(phone=conversation.contact_phone).first() or CustomerProfile.objects.create(
        phone=conversation.contact_phone, customer_type=CustomerProfile.INDIVIDUAL,
        first_name=first_name.strip()[:100], last_name=(last_name or '').strip()[:100],
        notes='Registered by Octos on WhatsApp.')
    return link_customer(conversation, customer)
