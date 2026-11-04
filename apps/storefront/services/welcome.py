"""
The welcome: one warm message to a customer the first time they are
registered, thanking them for choosing the business.

Sent once per phone number, ever, whichever channel carried it: the text
log and the WhatsApp thread are both checked, so it holds however many
times a customer is created, merged or re-registered.

One step for every channel: WhatsApp first, when the customer wrote to
us in the last 24 hours; SMS otherwise, and as the fallback if WhatsApp
fails. Here and nowhere else.

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


TITLES = {'mr', 'mrs', 'ms', 'mss', 'miss', 'mstr', 'master', 'dr', 'prof', 'rev', 'revd',
          'pastor', 'madam', 'mad', 'mdm', 'sir', 'hon', 'nana', 'togbe', 'apostle', 'bishop', 'eng', 'esq'}


def first_name(customer_or_name):
    """
    A first name worth greeting with, or '' to leave the greeting plain.
    Titles typed into the name ("Mss. Grace", "Dr Kofi") are skipped, and
    when a title filled the whole first-name box, the last-name box is read
    on: "Mss." + "Grace Adjorkor" greets Grace.
    """
    if isinstance(customer_or_name, str):
        words = customer_or_name.split()
    else:
        words = f'{customer_or_name.first_name or ""} {customer_or_name.last_name or ""}'.split()
    for word in words:
        raw = word.strip(".,;:")
        if raw.lower() in TITLES:
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z'-]{1,14}", raw):
            return ''
        if raw.lower() in NOT_NAMES:
            return ''
        return raw[:1].upper() + raw[1:].lower()
    return ''


def welcome_text(customer_or_name) -> str:
    name = first_name(customer_or_name)
    hello = f'Hi {name}, welcome' if name else 'Welcome'
    text = (f"{hello} to {business_name()}! Thank you for choosing us. "
            "Whatever you need printed, we're here for you.")
    return text if len(text) <= 160 else text.split(' Whatever')[0]


def already_welcomed(phone) -> bool:
    """
    True if this number has had its welcome on either channel: an SMS
    the provider accepted, or a WhatsApp welcome that has not failed.
    A queued one counts, so two registrations seconds apart can't both
    send. A failed WhatsApp welcome doesn't count; its SMS fallback,
    once accepted, does.
    """
    from apps.communications.models import Message
    from apps.core.phones import to_international
    from apps.storefront.models import TextMessage
    from apps.storefront.services.sms import _normalise

    number = _normalise(phone)
    if number and TextMessage.objects.filter(phone=number, kind=KIND, accepted=True).exists():
        return True

    international = to_international(phone or '')
    return bool(international) and (
        Message.objects
        .filter(channel=Message.WHATSAPP, direction=Message.OUTBOUND, kind=KIND,
                conversation__contact_phone=international)
        .exclude(status=Message.FAILED)
        .exists()
    )


def greet(phone, name='') -> bool:
    """
    The welcome to one phone number, if it has never had one. Never raises.
    Both doors lead here: a customer registered by staff, and an account
    made in the app (which creates a lead, not a customer).
    """
    from apps.communications.services.whatsapp_outbound import try_send_text
    from apps.storefront.services.sms import send_sms

    try:
        if not phone or already_welcomed(phone):
            return False
        text = welcome_text(name or '')
        if try_send_text(phone, text, kind=KIND):
            return True
        return send_sms(phone, text, kind=KIND)
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