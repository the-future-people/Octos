"""
Push notifications through Firebase Cloud Messaging.

The key is the Firebase service account, held in Railway's settings as
FIREBASE_SERVICE_ACCOUNT (the downloaded JSON, pasted whole). Without it
nothing is pushed and every message falls back to SMS, which is also
how tests and local development behave.
"""

import json
import logging
import os
import threading

import requests

logger = logging.getLogger(__name__)

SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'
_credentials = None
_lock = threading.Lock()


class TokenGone(Exception):
    """The phone no longer has the app, or the address is stale."""


def _creds():
    global _credentials
    raw = os.environ.get('FIREBASE_SERVICE_ACCOUNT')
    if not raw:
        return None
    with _lock:
        if _credentials is None:
            from google.oauth2 import service_account
            _credentials = service_account.Credentials.from_service_account_info(
                json.loads(raw), scopes=[SCOPE],
            )
        if not _credentials.valid:
            from google.auth.transport.requests import Request
            _credentials.refresh(Request())
        return _credentials


def configured():
    return bool(os.environ.get('FIREBASE_SERVICE_ACCOUNT'))


def send(token, title, body, data=None):
    """
    True when Firebase accepted the message for this phone. Raises
    TokenGone when the phone has gone, so its address can be forgotten.
    """
    creds = _creds()
    if creds is None:
        return False

    message = {
        'token': token,
        'notification': {'title': title, 'body': body},
        # Strings only: Firebase refuses anything else in data.
        'data': {k: str(v) for k, v in (data or {}).items()},
        'android': {'priority': 'HIGH'},
    }
    try:
        response = requests.post(
            f'https://fcm.googleapis.com/v1/projects/{creds.project_id}/messages:send',
            json={'message': message},
            headers={'Authorization': f'Bearer {creds.token}'},
            timeout=10,
        )
    except requests.RequestException:
        logger.exception('Push to a phone failed to send')
        return False

    if response.status_code == 200:
        return True
    if response.status_code in (400, 404) and 'UNREGISTERED' in response.text:
        raise TokenGone()
    logger.warning('Push refused (%s): %s', response.status_code, response.text[:300])
    return False



def nudge(token, data):
    """
    A silent message: data only, no title or body, so nothing shows on
    the phone. An open app hears it and refreshes. Raises TokenGone like
    send() when the phone has gone.
    """
    creds = _creds()
    if creds is None:
        return False
    try:
        response = requests.post(
            f'https://fcm.googleapis.com/v1/projects/{creds.project_id}/messages:send',
            json={'message': {
                'token': token,
                'data': {k: str(v) for k, v in (data or {}).items()},
                'android': {'priority': 'HIGH'},
            }},
            headers={'Authorization': f'Bearer {creds.token}'},
            timeout=10,
        )
    except requests.RequestException:
        logger.exception('Nudge to a phone failed to send')
        return False
    if response.status_code == 200:
        return True
    if response.status_code in (400, 404) and 'UNREGISTERED' in response.text:
        raise TokenGone()
    return False