"""
Talking to Paystack.

One module, so the rest of the system never builds an HTTP request to a
payment provider. If Paystack is ever replaced, this file is what
changes.

Nothing here raises. A provider's outage must leave an order exactly as
it was, so every call returns a dict with `success` in it and the caller
decides what to tell the customer.
"""

import logging

from decimal import Decimal

logger = logging.getLogger(__name__)

BASE_URL = 'https://api.paystack.co'
TIMEOUT = 15


def initialise(reference, amount_minor, email, callback_url=None, metadata=None):
    """
    Hand a payment to Paystack and get somewhere to send the customer.

    `reference` is ours. It comes back on the webhook, so it has to name
    the order without a lookup table in between.

    `amount_minor` is in pesewas, which is what Paystack takes — a
    cedi amount sent here by mistake would charge a hundredth of what
    was meant.
    """
    from django.conf import settings

    secret = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
    if not secret:
        logger.error('Paystack is not configured — no secret key')
        return {'success': False, 'error': 'Payments are not set up yet.'}

    payload = {
        'reference': reference,
        'amount': int(amount_minor),
        'email': email,
        'currency': 'GHS',
    }
    if callback_url:
        payload['callback_url'] = callback_url
    if metadata:
        payload['metadata'] = metadata

    try:
        import requests
        response = requests.post(
            f'{BASE_URL}/transaction/initialize',
            headers={'Authorization': f'Bearer {secret}'},
            json=payload,
            timeout=TIMEOUT,
        )
        body = response.json()
    except Exception:
        # Their outage, not our order's problem.
        logger.warning('Paystack initialise failed for %s', reference, exc_info=True)
        return {'success': False, 'error': 'Could not reach the payment provider.'}

    if response.status_code >= 400 or not body.get('status'):
        logger.warning(
            'Paystack refused %s: %s %s',
            reference, response.status_code, str(body)[:300],
        )
        return {
            'success': False,
            'error': body.get('message') or 'The payment provider refused this.',
        }

    data = body.get('data') or {}
    return {
        'success': True,
        'authorization_url': data.get('authorization_url'),
        'access_code': data.get('access_code'),
        'reference': data.get('reference') or reference,
    }


def verify(reference):
    """
    Ask Paystack what happened to a payment.

    The webhook is what marks an order paid; this exists for the cases
    the webhook cannot cover — a customer who returns to the page before
    the event arrives, and reconciling anything that looks wrong later.
    """
    from django.conf import settings

    secret = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
    if not secret:
        return {'success': False, 'error': 'Payments are not set up yet.'}

    try:
        import requests
        response = requests.get(
            f'{BASE_URL}/transaction/verify/{reference}',
            headers={'Authorization': f'Bearer {secret}'},
            timeout=TIMEOUT,
        )
        body = response.json()
    except Exception:
        logger.warning('Paystack verify failed for %s', reference, exc_info=True)
        return {'success': False, 'error': 'Could not reach the payment provider.'}

    if response.status_code >= 400 or not body.get('status'):
        return {'success': False, 'error': body.get('message') or 'Not found.'}

    data = body.get('data') or {}
    return {
        'success': True,
        'paid': data.get('status') == 'success',
        'amount_minor': data.get('amount') or 0,
        'channel': data.get('channel') or '',
        'provider_id': str(data.get('id') or ''),
        'raw': data,
    }


def to_minor(amount):
    """Cedis to pesewas. Paystack takes the smallest unit."""
    return int((Decimal(str(amount)) * 100).quantize(Decimal('1')))