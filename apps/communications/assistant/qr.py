"""
The counter QR's invisible signature (Layer 2, Step 2.1, 11 Nov 2026).

The printed QR opens WhatsApp with "Hi Farhat 👋" ready to send. Customers keep
a greeting that sounds like them, and delete anything that looks like a form,
so the proof travels inside the greeting, invisibly:

    what the customer sees:  Hi Farhat 👋
    what Octos receives:     Hi Farhat 👋 + 10 variation selectors

Tested on a real phone, 11 Nov 2026: WhatsApp strips zero-width characters
(U+200B and friends), but keeps the variation selectors that belong to emoji
(U+E0100 onwards), since removing them would break emoji. So each signature
character is a variation selector carrying 4 bits (U+E0100 + 0..15).

The 40 bits are 16 for the branch and 24 of HMAC-SHA256 over the branch, keyed
from SECRET_KEY: only this server can make a valid one, and a guess passes about
once in 16.7 million. A customer who types their own "Hi" simply sends no
signature, and Octos falls back to the clues and the attendant's tap.
"""
import hashlib
import hmac
from urllib.parse import quote

from django.conf import settings

BASE = 0xE0100                          # VARIATION SELECTOR-17
NIBBLE = range(BASE, BASE + 16)         # the 16 we use: 4 bits each
SELECTORS = range(BASE, BASE + 240)     # the whole supplement, stripped on cleaning
ZERO_WIDTH = {'\u200b', '\u200c', '\u200d', '\u2060', '\ufeff'}
BRANCH_BITS, SIG_BITS = 16, 24
CHARS = (BRANCH_BITS + SIG_BITS) // 4   # 10
GREETING = 'Hi Farhat \U0001F44B'       # Hi Farhat 👋


def _signature(branch_id):
    key = hashlib.sha256(('counter-qr:' + settings.SECRET_KEY).encode()).digest()
    digest = hmac.new(key, f'counter:{branch_id}'.encode(), hashlib.sha256).digest()
    return int.from_bytes(digest[:SIG_BITS // 8], 'big')


def encode(branch_id):
    """The invisible signature for a branch: 10 variation selectors."""
    value = (branch_id << SIG_BITS) | _signature(branch_id)
    nibbles = [(value >> (4 * i)) & 0xF for i in reversed(range(CHARS))]
    return ''.join(chr(BASE + n) for n in nibbles)


def decode(text):
    """
    (branch_id, True) for a valid signature, (branch_id, False) for one that
    fails its check, (None, False) when there is none.
    """
    nibbles = [ord(c) - BASE for c in (text or '') if ord(c) in NIBBLE]
    if len(nibbles) != CHARS:
        return None, False
    value = 0
    for n in nibbles:
        value = (value << 4) | n
    branch_id = value >> SIG_BITS
    given = value & ((1 << SIG_BITS) - 1)
    ok = hmac.compare_digest(given.to_bytes(3, 'big'), _signature(branch_id).to_bytes(3, 'big'))
    return branch_id, ok


def clean(text):
    """The text as a person reads it: the signature and any zero-width characters removed."""
    return ''.join(c for c in (text or '')
                   if ord(c) not in SELECTORS and c not in ZERO_WIDTH).strip()


def has_invisible(text):
    return any(ord(c) in SELECTORS or c in ZERO_WIDTH for c in (text or ''))


def link(branch_id, number):
    """The wa.me link the printed QR holds: the greeting, plus its signature."""
    digits = ''.join(c for c in str(number) if c.isdigit())
    return f'https://wa.me/{digits}?text={quote(GREETING + encode(branch_id))}'
