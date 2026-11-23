"""
Partner reps log in with their number and a password (24 Nov 2026).

The password is chosen at registration, confirmed by the code sent to the
rep's phone, and kept only as a hash. Logging in gives an ordinary Print
Octos session (the same AppSession app customers have), which is what the
portal sends with every request.

Five wrong passwords for a number lock it for fifteen minutes. Forgotten:
a code to the phone, and a new password.
"""
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

MAX_TRIES = 5
LOCKED_FOR = 15 * 60


class Refused(Exception):
    def __init__(self, message, field=''):
        super().__init__(message)
        self.field = field


def check_new(raw):
    """A password good enough to keep, or Refused saying what's wrong."""
    raw = raw or ''
    if len(raw) < 8:
        raise Refused('Use at least 8 characters for your password.', 'password')
    try:
        validate_password(raw)
    except ValidationError as exc:
        raise Refused(' '.join(exc.messages), 'password')
    return make_password(raw)


def session(lead, device='partners-web'):
    """A fresh session for this person. The token is returned once, never stored as is."""
    from apps.storefront.models import AppSession
    from apps.storefront.services.accounts import _hash_token
    token = secrets.token_urlsafe(32)
    AppSession.objects.create(lead=lead, token_hash=_hash_token(token), device=device[:120],
                              last_seen_at=timezone.now())
    return token


def _rep(phone):
    from apps.partners.models import PartnerRep
    return (PartnerRep.objects.select_related('lead', 'partner')
            .filter(lead__phone=phone, is_active=True).order_by('-partner__applied_at').first())


def _tries_key(phone):
    return f'partners:login:{phone}'


def login(raw_phone, password):
    """(rep, token) for the right number and password; Refused otherwise."""
    from apps.storefront.services.accounts import normalise_phone
    phone = normalise_phone(raw_phone)
    if not phone:
        raise Refused('Enter your number, like 024 000 0000.', 'phone')
    tries = cache.get(_tries_key(phone)) or 0
    if tries >= MAX_TRIES:
        raise Refused('Too many wrong passwords. Wait 15 minutes, or set a new one with a code.', 'password')
    rep = _rep(phone)
    if rep is None or not rep.password or not check_password(password or '', rep.password):
        cache.set(_tries_key(phone), tries + 1, LOCKED_FOR)
        raise Refused('That number and password don\'t match.', 'password')
    cache.delete(_tries_key(phone))
    return rep, session(rep.lead)


def send_reset_code(raw_phone):
    """A code to a rep's phone for a new password. Says nothing about whether the number is a rep's."""
    from apps.storefront.services import accounts
    phone = accounts.normalise_phone(raw_phone)
    if not phone:
        raise Refused('Enter your number, like 024 000 0000.', 'phone')
    if _rep(phone) is not None:
        try:
            accounts.send_code(phone)
        except accounts.AccountRefused as exc:
            raise Refused(str(exc), 'phone')
    return accounts.mask(phone)


def reset(raw_phone, code, password):
    """The code was right: the new password is set and they're logged in. (rep, token)."""
    from apps.storefront.services import accounts
    hashed = check_new(password)
    try:
        phone = accounts.check_code(raw_phone, code)
    except accounts.AccountRefused as exc:
        raise Refused(str(exc), 'code')
    rep = _rep(phone)
    if rep is None:
        raise Refused('That number isn\'t on a partner account.', 'phone')
    rep.password = hashed
    rep.save(update_fields=['password', 'updated_at'])
    cache.delete(_tries_key(phone))
    return rep, session(rep.lead)
