"""
The WhatsApp Cloud API, and nothing else.

Two calls: send_text and send_template. Each returns Meta's message id
(the wamid that delivery statuses will refer to) or raises WhatsAppError
with Meta's own code and reason. No window rules, no database: those
belong to whoever calls this, so this file stays small enough to trust.
"""
import logging

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.core.phones import to_international

logger = logging.getLogger(__name__)

# The version Meta subscribed our webhook at (4 Nov 2026). Change it on
# purpose, after reading Meta's changelog, never as a side effect.
API_VERSION = 'v26.0'
TIMEOUT = 20


class WhatsAppError(Exception):
    """Meta refused, or never answered. code is Meta's, or 'network'."""

    def __init__(self, code, message, details=''):
        self.code = str(code)
        self.message = message
        self.details = details
        super().__init__(f'{self.code}: {message}' + (f' ({details})' if details else ''))


def send_text(phone, body):
    """Free text. Meta accepts it only inside the customer's 24-hour window."""
    return _send(phone, {
        'type': 'text',
        'text': {'preview_url': False, 'body': body},
    })


def send_template(phone, name, language='en', params=()):
    """An approved template, with its body's {{1}}, {{2}}… filled in order."""
    template = {'name': name, 'language': {'code': language}}
    if params:
        template['components'] = [{
            'type': 'body',
            'parameters': [{'type': 'text', 'text': str(p)} for p in params],
        }]
    return _send(phone, {'type': 'template', 'template': template})


def _send(phone, message):
    token = settings.WHATSAPP_ACCESS_TOKEN
    number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    if not token or not number_id:
        raise ImproperlyConfigured('WhatsApp access token or phone number id is not set.')

    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': _recipient(phone),
        **message,
    }
    try:
        response = requests.post(
            f'https://graph.facebook.com/{API_VERSION}/{number_id}/messages',
            headers={'Authorization': f'Bearer {token}'},
            json=payload,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise WhatsAppError('network', str(exc)) from exc

    try:
        data = response.json()
    except ValueError:
        raise WhatsAppError(response.status_code, 'Meta answered with something that is not JSON')

    if 'error' in data:
        error = data['error']
        raise WhatsAppError(
            error.get('code', response.status_code),
            error.get('message', 'unknown error'),
            (error.get('error_data') or {}).get('details', ''),
        )

    try:
        return data['messages'][0]['id']
    except (KeyError, IndexError, TypeError):
        raise WhatsAppError(response.status_code, f'no message id in the answer: {data!r}')


def _recipient(phone):
    """
    The number as Meta wants it: international, digits only, no '+'.
    A number that isn't real is refused here, before Meta is asked.
    """
    international = to_international(phone or '')
    if not international:
        raise WhatsAppError('invalid_number', f'not a real phone number: {phone!r}')
    return international.lstrip('+')

def show_typing(wamid):
    """
    Mark a customer's message as read and show them "typing..." while Octos
    prepares a reply. WhatsApp removes it when the reply arrives or after
    25 seconds. Cosmetic: a failure is logged, never raised.
    """
    phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
    token = settings.WHATSAPP_ACCESS_TOKEN
    if not (wamid and phone_id and token):
        return False
    try:
        response = requests.post(
            f'https://graph.facebook.com/{API_VERSION}/{phone_id}/messages',
            headers={'Authorization': f'Bearer {token}'},
            json={'messaging_product': 'whatsapp', 'status': 'read', 'message_id': wamid,
                  'typing_indicator': {'type': 'text'}},
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        logger.warning('Could not show typing for %s', wamid, exc_info=True)
        return False
    if response.status_code != 200:
        logger.warning('Typing for %s refused: %s %s', wamid, response.status_code, response.text[:200])
        return False
    return True


def upload_media(content, filename, mime):
    """Upload a file to Meta for sending; returns its media id."""
    token = settings.WHATSAPP_ACCESS_TOKEN
    number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    if not token or not number_id:
        raise ImproperlyConfigured('WhatsApp access token or phone number id is not set.')
    try:
        response = requests.post(
            f'https://graph.facebook.com/{API_VERSION}/{number_id}/media',
            headers={'Authorization': f'Bearer {token}'},
            data={'messaging_product': 'whatsapp', 'type': mime},
            files={'file': (filename, content, mime)},
            timeout=TIMEOUT * 3,
        )
    except requests.RequestException as exc:
        raise WhatsAppError('network', str(exc)) from exc
    try:
        data = response.json()
    except ValueError:
        raise WhatsAppError(response.status_code, 'Meta answered the upload with something that is not JSON')
    if 'error' in data:
        error = data['error']
        raise WhatsAppError(error.get('code', response.status_code), error.get('message', 'upload refused'))
    if not data.get('id'):
        raise WhatsAppError(response.status_code, f'no media id in the answer: {data!r}')
    return data['id']


def send_image(phone, content, filename, caption=''):
    """An image (a card), uploaded then sent, with a caption whose links can be tapped."""
    image = {'id': upload_media(content, filename, 'image/png')}
    if caption:
        image['caption'] = caption
    return _send(phone, {'type': 'image', 'image': image})
