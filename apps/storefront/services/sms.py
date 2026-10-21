
"""
Sending a text message.

One function, so the rest of the system never knows which provider is
behind it. mNotify today; the call lives here and nothing else changes
if that ever stops being true.

Never raises. A customer whose code did not reach them by SMS still has
it on screen, and an order must not fail because a message did not go
out.
"""

import logging

logger = logging.getLogger(__name__)


def send_sms(phone, message):
    """
    Returns True if the provider accepted it, False otherwise. The
    caller carries on either way.
    """
    from django.conf import settings

    api_key = getattr(settings, 'MNOTIFY_API_KEY', '')
    sender = getattr(settings, 'MNOTIFY_SENDER_ID', 'Farhat')

    if not api_key:
        # Not configured yet. Logged rather than failed, so the flow can
        # be built and tested before the integration lands.
        logger.info('SMS not sent (no API key) — to %s: %s', phone, message)
        return False

    # Only a real number is sent to: a message to a broken one is paid
    # for and reaches nobody.
    number = _normalise(phone)
    if not number:
        logger.warning('SMS not sent: %r is not a real phone number', phone)
        return False

    try:
        import requests
        response = requests.post(
            'https://api.mnotify.com/api/sms/quick',
            params={'key': api_key},
            json={
                'recipient': [number],
                'sender': sender,
                'message': message,
                'is_schedule': False,
            },
            timeout=10,
        )
        if response.status_code >= 400:
            logger.warning(
                'SMS refused for %s: %s %s',
                phone, response.status_code, response.text[:200],
            )
            return False
        return True
    except Exception:
        # Deliberately broad. Nothing a message provider does should
        # take down an order.
        logger.warning('SMS failed for %s', phone, exc_info=True)
        return False


def _normalise(phone):
    """
    The number as mNotify wants it: international, digits only
    (233244111222, 15145828114). None for a number that is not real,
    which is then not sent: a message to a broken number is paid for and
    reaches nobody.
    """
    from apps.core.phones import to_international
    number = to_international(phone)
    return number[1:] if number else None