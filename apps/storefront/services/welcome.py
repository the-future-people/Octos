"""
The welcome: one warm message to a customer the first time they are
registered, thanking them for choosing the business.

Sent once per phone number, ever. The text log decides that, so it holds
however many times a customer is created, merged or re-registered.

One step for every channel: SMS today; once WhatsApp is connected it is
tried first and SMS becomes the fallback, here and nowhere else.

Plain ASCII on purpose: a single curly apostrophe turns an SMS into
Unicode, which halves its length and doubles its cost.
"""

import logging
import re

from django.conf import settings

logger = logging.getLogger(__name__)

KIND = 'welcome'
NOT_NAMES = {'customer', 'walk', 'walkin', 'walk-in', 'test', 'unknown', 'na', 'n/a', 'none', 'mr', 'mrs', 'ms'}


def business_name():
    return getattr(settings, 'BUSINESS_NAME', 'Farhat Printing Press')


def first_name(customer_or_name):
    """A first name worth greeting with, or '' to leave the greeting plain."""
    given = customer_or_name if isinstance(customer_or_name, str) else (customer_or_name.first_name or '')
    raw = given.strip().split(' ')[0]
    if not re.fullmatch(r"[A-Za-z][A-Za-z'-]{1,14}", raw or ''):
        return ''
    if raw.lower() in NOT_NAMES:
        return ''
    return raw[:1].upper() + raw[1:].lower()


def welcome_text(customer_or_name) -> str:
    name = first_name(customer_or_name)
    hello = f'Hi {name}, welcome' if name else 'Welcome'
    text = (f"{hello} to {business_name()}! Thank you for choosing us. "
            "Whatever you need printed, we're here for you.")
    return text if len(text) <= 160 else text.split(' Whatever')[0]


def already_welcomed(phone) -> bool:
    from apps.storefront.models import TextMessage
    from apps.storefront.services.sms import _normalise
    number = _normalise(phone)
    return bool(number) and TextMessage.objects.filter(phone=number, kind=KIND, accepted=True).exists()


def greet(phone, name='') -> bool:
    """
    The welcome to one phone number, if it has never had one. Never raises.
    Both doors lead here: a customer registered by staff, and an account
    made in the app (which creates a lead, not a customer).
    """
    from apps.storefront.services.sms import send_sms

    try:
        if not phone or already_welcomed(phone):
            return False
        # WhatsApp goes here first, once connected; SMS stays the fallback.
        return send_sms(phone, welcome_text(name or ''), kind=KIND)
    except Exception:
        logger.warning('Welcome not sent to %s', phone, exc_info=True)
        return False


def welcome(customer_id) -> bool:
    """The welcome for a customer registered by staff. Never raises."""
    from apps.customers.models import CustomerProfile

    try:
        customer = CustomerProfile.objects.get(pk=customer_id)
    except CustomerProfile.DoesNotExist:
        return False
    if customer.is_walkin:
        return False
    return greet(customer.phone, customer.first_name or '')
