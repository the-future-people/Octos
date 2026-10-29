"""
Accounts for the Print Octos app: a phone number, verified once by a code
sent to it, and a session the app keeps.

The number is the account. It is the Lead the website already makes, so
orders placed on the website with the same number are already theirs.

The code is six digits, lives ten minutes, and is kept only as a hash in
the cache. Five wrong guesses kill it. A number receives at most three
codes in fifteen minutes, so nobody can flood someone's phone or run up
the SMS bill; the views add a limit per device on top.
"""

import hashlib
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

CODE_TTL = 10 * 60
MAX_GUESSES = 5
SENDS_PER_WINDOW = 3
SEND_WINDOW = 15 * 60


class AccountRefused(Exception):
    """Something the customer can fix, and the message says what."""


# ── Phone numbers ────────────────────────────────────────────────

def normalise_phone(raw):
    """
    One form for one number: the international form, through the one
    phone rule for all of Octos. 024 499 9888, +233 24 499 9888 and
    233244999888 are all +233244999888; a number from abroad is kept as
    its own country's, so a foreign customer can order and sign in.
    None for anything that is not a real number.

    Numbers already stored as 0XXXXXXXXX still match, because every
    comparison here converts both sides.
    """
    from apps.core.phones import to_international
    return to_international(raw)


def find_lead(phone):
    """
    The account for this number, however the website stored it. Numbers
    were stored much as they were typed, so they are compared normalised.
    """
    from apps.storefront.models import Lead

    # Compare like with like: the number as typed (0556244194) must find
    # the lead stored in the one form (+233556244194). Comparing the raw
    # input made a second lead for a returning customer.
    target = normalise_phone(phone) or (phone or '').strip()
    if not target:
        return None

    exact = Lead.objects.filter(phone=target).first()
    if exact:
        return exact
    for lead in Lead.objects.filter(phone__contains=target[-4:]):
        if normalise_phone(lead.phone) == target:
            return lead
    return None


# ── The code ─────────────────────────────────────────────────────

def _code_key(phone):
    return f'account:code:{phone}'


def _sends_key(phone):
    return f'account:sends:{phone}'


def send_code(raw_phone):
    """Text a fresh code to the number. Returns the normalised number."""
    from apps.storefront.services.sms import send_sms

    phone = normalise_phone(raw_phone)
    if phone is None:
        raise AccountRefused('Enter a Ghanaian mobile number, like 024 000 0000.')

    now = timezone.now().timestamp()
    sends = [t for t in (cache.get(_sends_key(phone)) or []) if now - t < SEND_WINDOW]
    if len(sends) >= SENDS_PER_WINDOW:
        raise AccountRefused(
            'We have sent several codes to this number. Wait a few minutes and try again.'
        )

    code = f'{secrets.randbelow(1_000_000):06d}'
    cache.set(_code_key(phone), {'hash': make_password(code), 'guesses': 0}, CODE_TTL)
    cache.set(_sends_key(phone), sends + [now], SEND_WINDOW)

    from apps.storefront.services.messages import code_text
    send_sms(phone, code_text(code))
    return phone


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def verify_code(raw_phone, code, first_name='', device=''):
    """
    Check the code. Right: the account (made now if the number is new) and
    a fresh session token, returned once and never stored as is.
    """
    from apps.storefront.models import AppSession, Lead

    phone = normalise_phone(raw_phone)
    if phone is None:
        raise AccountRefused('Enter a Ghanaian mobile number, like 024 000 0000.')

    held = cache.get(_code_key(phone))
    if not held:
        raise AccountRefused('That code has expired. Ask for a new one.')

    if not check_password(str(code or '').strip(), held['hash']):
        held['guesses'] += 1
        if held['guesses'] >= MAX_GUESSES:
            cache.delete(_code_key(phone))
            raise AccountRefused('Too many wrong codes. Ask for a new one.')
        cache.set(_code_key(phone), held, CODE_TTL)
        raise AccountRefused('That code is not right. Check the message and try again.')

    cache.delete(_code_key(phone))

    lead = find_lead(phone)
    if lead is None:
        name = (first_name or '').strip()
        if not name:
            raise AccountRefused('Tell us your first name to finish signing up.')
        lead = Lead.objects.create(phone=phone, first_name=name[:100])
    elif first_name and not lead.first_name:
        lead.first_name = first_name.strip()[:100]
        lead.save(update_fields=['first_name'])

    token = secrets.token_urlsafe(32)
    AppSession.objects.create(
        lead=lead, token_hash=_hash_token(token),
        device=(device or '')[:120], last_seen_at=timezone.now(),
    )
    return lead, token


# ── Sessions ─────────────────────────────────────────────────────

def session_for(token):
    """The active session for a token, or None."""
    from apps.storefront.models import AppSession

    if not token:
        return None
    session = (
        AppSession.objects
        .select_related('lead')
        .filter(token_hash=_hash_token(token), revoked_at__isnull=True)
        .first()
    )
    if session is None:
        return None
    # Kept roughly current without a write on every request.
    now = timezone.now()
    if not session.last_seen_at or (now - session.last_seen_at).total_seconds() > 3600:
        session.last_seen_at = now
        session.save(update_fields=['last_seen_at'])
    return session


def sign_out(session):
    session.revoked_at = timezone.now()
    session.save(update_fields=['revoked_at'])


def mask(phone):
    """
    A number shown without giving it away: 024 ••• 9888 for Ghana, and
    the country code for anywhere else (+1 ••• 8114). Built from how the
    number is displayed, so it reads the way people know their own number.
    """
    from apps.core.phones import display, to_international
    number = to_international(phone) or str(phone or '')
    shown = display(number)
    digits = ''.join(c for c in number if c.isdigit())
    head = shown.split(' ')[0] if ' ' in shown else shown[:3]
    return f'{head} ••• {digits[-4:]}'

# ── My orders ────────────────────────────────────────────────────

def leads_for(lead):
    """
    Every Lead on this number, however the website wrote it down: an
    order placed as "024 499 9888" and one as "0244999888" are the same
    customer's.
    """
    from apps.storefront.models import Lead

    phone = normalise_phone(lead.phone) or lead.phone
    same = [
        other for other in Lead.objects.filter(phone__contains=phone[-4:])
        if normalise_phone(other.phone) == phone
    ]
    return same or [lead]


# The customer's words for where an order has got to.
_STAGE = {
    'RECEIVED': 'inspecting',
    'IN_PRODUCTION': 'press',
    'FINISHING': 'finishing',
    'QUALITY_CHECK': 'finishing',
    'DONE': 'ready',
}


def _stage(order):
    job = order.job
    if job is None:
        return 'paid'
    if job.handover_state == 'HANDED_OVER':
        return 'collected'
    return _STAGE.get(job.work_state, 'paid')


def _detail(line):
    """A short line about the piece: 3ft × 6ft, 100 copies, 2 boxes."""
    specs = line.get('specifications') or {}
    quantity = int(line.get('quantity') or 1)
    w, h = specs.get('width_in'), specs.get('height_in')
    if w and h:
        def size(inches):
            inches = float(inches)
            return f'{inches / 12:g}ft' if inches % 12 == 0 else f'{inches:g}in'
        piece = f'{size(w)} × {size(h)}'
        return piece if quantity == 1 else f'{piece} · {quantity} pieces'
    name = (line.get('base_name') or line.get('service_name') or '').lower()
    if 'card' in name:
        return f'{quantity} box' if quantity == 1 else f'{quantity} boxes'
    return f'{quantity} copy' if quantity == 1 else f'{quantity} copies'


def orders_for(lead):
    """
    The customer's paid orders, newest first: active ones with their stage
    and time left, collected ones with when, cancelled ones kept apart.
    Carts never paid for are not orders.
    """
    from apps.jobs.models import JobStatusLog
    from apps.jobs.services.estimates import estimate
    from apps.storefront.models import OnlineOrder

    orders = (
        OnlineOrder.objects
        .filter(lead__in=leads_for(lead), paid_at__isnull=False)
        .select_related('job', 'branch')
        .order_by('-paid_at')
    )

    active, collected, cancelled = [], [], []
    for order in orders:
        job = order.job
        lines = order.line_items or []
        first = lines[0] if lines else {}
        name = first.get('service_name', 'Order')
        item = {
            'order_number': order.order_number,
            # Their own order: the link that opens its tracking page.
            'token': order.access_token,
            'summary': name if len(lines) <= 1 else f'{name} and {len(lines) - 1} more',
            # The service's own name, which badges and photos are found by.
            'base_name': first.get('base_name') or name,
            'detail': _detail(first) if first else '',
            'total': f'{order.total:.2f}',
            'paid_at': order.paid_at.isoformat(),
            'branch': order.branch.name if order.branch_id else None,
            'promised_for': order.promised_for.isoformat() if order.promised_for else None,
            'stage': _stage(order),
            # Every line with its add-ons and prices, so the list can open
            # an order in place without asking again.
            'lines': [{
                'name': line.get('service_name', ''),
                'detail': _detail(line),
                'total': str(line.get('total') or ''),
                'addons': [{
                    'name': addon.get('service_name', ''),
                    'detail': addon.get('detail', ''),
                    'total': str(addon.get('total') or '0'),
                } for addon in (line.get('addons') or [])],
            } for line in lines],
        }

        if job is not None and job.status in ('CANCELLED', 'VOIDED'):
            item['stage'] = 'cancelled'
            cancelled.append(item)
        elif item['stage'] == 'collected':
            at = (
                JobStatusLog.objects
                .filter(job=job, to_status='HANDED_OVER')
                .order_by('transitioned_at')
                .values_list('transitioned_at', flat=True)
                .first()
            )
            item['collected_at'] = (at or job.updated_at).isoformat()
            collected.append(item)
        else:
            if item['stage'] == 'ready':
                done = (
                    JobStatusLog.objects
                    .filter(job=job, to_status='DONE')
                    .order_by('transitioned_at')
                    .values_list('transitioned_at', flat=True)
                    .first()
                )
                item['ready_since'] = (done or job.updated_at).isoformat()
            try:
                found = estimate(job) if job is not None else None
            except Exception:
                found = None
            item['estimate'] = found.as_dict() if found else None
            active.append(item)

    return {'active': active, 'collected': collected, 'cancelled': cancelled}