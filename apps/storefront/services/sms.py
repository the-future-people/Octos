
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

    try:
        import requests
        response = requests.post(
            'https://api.mnotify.com/api/sms/quick',
            params={'key': api_key},
            json={
                'recipient': [_normalise(phone)],
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
    0244111222 becomes 233244111222. Ghanaian numbers are given with a
    leading zero and sent with a country code.
    """
    digits = ''.join(c for c in str(phone) if c.isdigit())
    if digits.startswith('233'):
        return digits
    return '233' + digits.lstrip('0')