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


def first_name(customer):
    """A first name worth greeting with, or '' to leave the greeting plain."""
    raw = (customer.first_name or '').strip().split(' ')[0]
    if not re.fullmatch(r"[A-Za-z][A-Za-z'-]{1,14}", raw or ''):
        return ''
    if raw.lower() in NOT_NAMES:
        return ''
    return raw[:1].upper() + raw[1:].lower()


def welcome_text(customer) -> str:
    name = first_name(customer)
    hello = f'Hi {name}, welcome' if name else 'Welcome'
    text = (f"{hello} to {business_name()}! Thank you for choosing us. "
            "Whatever you need printed, we're here for you.")
    return text if len(text) <= 160 else text.split(' Whatever')[0]


def already_welcomed(phone) -> bool:
    from apps.storefront.models import TextMessage
    from apps.storefront.services.sms import _normalise
    number = _normalise(phone)
    return bool(number) and TextMessage.objects.filter(phone=number, kind=KIND, accepted=True).exists()


def welcome(customer_id) -> bool:
    """Send the welcome to one customer, if they have not had it. Never raises."""
    from apps.customers.models import CustomerProfile
    from apps.storefront.services.sms import send_sms

    try:
        customer = CustomerProfile.objects.get(pk=customer_id)
        if customer.is_walkin or not customer.phone or already_welcomed(customer.phone):
            return False
        # WhatsApp goes here first, once connected; SMS stays the fallback.
        return send_sms(customer.phone, welcome_text(customer), kind=KIND)
    except Exception:
        logger.warning('Welcome not sent to customer %s', customer_id, exc_info=True)
        return False
