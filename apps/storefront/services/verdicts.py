"""
A verdict the server can trust when it comes back.

Artwork is judged before anything is committed — while the customer can
still act on it, which is the only moment the warning is worth giving.
At that point there is no order to store the verdict against, so it
travels with the customer instead.

Which means it has to be worth something on its return. A browser
holding an unsigned "this file passed" is a browser that can claim
anything, and the hole that opens is specific: upload good artwork, get
a pass, swap in a screenshot, commit. The floor receives something
nobody checked.

So the verdict is signed, and it carries what it was judged against —
the file's hash, the service, the dimensions. The commit re-hashes the
file it is given and refuses a claim that does not match. A verdict for
a different file, a different size, or an edited claim is worthless.

The signature is HMAC over the serialised claim with Django's secret
key. Nothing secret is inside it: a customer can read their own
verdict, which is fine, because the protection is against alteration
rather than disclosure.
"""

import base64
import hashlib
import hmac
import json
import logging
import time

from django.conf import settings

logger = logging.getLogger(__name__)

# Long enough to specify a banner and press the button, short enough
# that a token found in a log tomorrow is useless.
DEFAULT_AGE_SECONDS = 60 * 60


def file_hash(upload):
    """
    What makes this file this file.

    Read in chunks: print artwork runs to tens of megabytes and reading
    it whole to hash it would hold all of that in memory for every
    upload.

    Reopened first, because whatever read it last may have closed it —
    Django does exactly that to an upload once it has been consumed,
    and the hash has to see the same bytes the measuring did.
    """
    upload.seek(0)
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def sign_claim(claim, age_seconds=DEFAULT_AGE_SECONDS):
    """
    A claim the server will recognise on its way back.

    age_seconds may be negative, which produces an already-expired
    token — only useful for proving that expiry is enforced.
    """
    body = dict(claim)
    body['expires'] = int(time.time()) + age_seconds

    raw = json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
    payload = base64.urlsafe_b64encode(raw).decode().rstrip('=')
    return f'{payload}.{_signature(payload)}'


def read_token(token):
    """
    The claim inside, or None.

    None for anything that is not exactly right: a bad signature, an
    expired claim, something that will not parse. The caller treats all
    of those the same way — as no verdict at all — because a token that
    cannot be verified tells us nothing about the file.
    """
    if not token or '.' not in token:
        return None

    payload, _, given = token.rpartition('.')

    if not hmac.compare_digest(_signature(payload), given):
        logger.warning('Artwork verdict token with a bad signature')
        return None

    try:
        padding = '=' * (-len(payload) % 4)
        claim = json.loads(base64.urlsafe_b64decode(payload + padding))
    except (ValueError, TypeError):
        logger.warning('Artwork verdict token that would not parse')
        return None

    if claim.get('expires', 0) < time.time():
        return None

    return claim


def claim_matches(claim, service_id, specifications, upload_hash):
    """
    Whether this verdict was about what is now being committed.

    All three have to hold. The file alone is not enough — the same
    artwork is fine on a card and unprintable across six feet, so a
    verdict carries the size it was judged at and a changed size
    retires it.
    """
    if not claim:
        return False
    if str(claim.get('service')) != str(service_id):
        return False
    if claim.get('file_hash') != upload_hash:
        return False

    judged = claim.get('specifications') or {}
    for key in ('width_in', 'height_in', 'pages'):
        if str(judged.get(key)) != str((specifications or {}).get(key)):
            return False

    return True


def _signature(payload):
    secret = settings.SECRET_KEY.encode()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:32]