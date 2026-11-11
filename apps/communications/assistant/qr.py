"""
The counter QR's invisible signature (Layer 2, Step 2.1, 11 Nov 2026).

The printed QR opens WhatsApp with "Hi Farhat 👋" ready to send. Customers keep
a greeting that sounds like them, and delete anything that looks like a form,
so the proof travels inside the greeting, invisibly:

    what the customer sees:  Hi Farhat 👋
    what Octos receives:     Hi Farhat 👋 + 40 zero-width characters

Two zero-width characters are bits (U+200B = 0, U+200C = 1), between two word
joiners (U+2060). The 40 bits are 16 for the branch and 24 of HMAC-SHA256 over
the branch, keyed from SECRET_KEY: only this server can make a valid one, and a
guess passes about once in 16.7 million. If WhatsApp strips the characters, or
the customer types their own "Hi", there is simply no signature, and Octos
falls back to the clues and the attendant's tap.
"""
import hashlib
import hmac
from urllib.parse import quote

from django.conf import settings

ZERO, ONE, MARK = '\u200b', '\u200c', '\u2060'
INVISIBLE = {ZERO, ONE, MARK, '\u200d', '\ufeff'}
BRANCH_BITS, SIG_BITS = 16, 24
GREETING = 'Hi Farhat \U0001F44B'          # Hi Farhat 👋


def _signature(branch_id):
    key = hashlib.sha256(('counter-qr:' + settings.SECRET_KEY).encode()).digest()
    digest = hmac.new(key, f'counter:{branch_id}'.encode(), hashlib.sha256).digest()
    return int.from_bytes(digest[:SIG_BITS // 8], 'big')


def _bits(value, width):
    return format(value, f'0{width}b')


def encode(branch_id):
    """The invisible signature for a branch."""
    bits = _bits(branch_id, BRANCH_BITS) + _bits(_signature(branch_id), SIG_BITS)
    return MARK + ''.join(ONE if b == '1' else ZERO for b in bits) + MARK


def decode(text):
    """
    (branch_id, True) for a valid signature, (branch_id, False) for one that
    fails its check, (None, False) when there is none.
    """
    text = text or ''
    start = text.find(MARK)
    end = text.find(MARK, start + 1) if start != -1 else -1
    if start == -1 or end == -1:
        return None, False
    inner = text[start + 1:end]
    if len(inner) != BRANCH_BITS + SIG_BITS or set(inner) - {ZERO, ONE}:
        return None, False
    bits = ''.join('1' if c == ONE else '0' for c in inner)
    branch_id = int(bits[:BRANCH_BITS], 2)
    given = int(bits[BRANCH_BITS:], 2)
    expected = _signature(branch_id)
    ok = hmac.compare_digest(given.to_bytes(3, 'big'), expected.to_bytes(3, 'big'))
    return branch_id, ok


def clean(text):
    """The text as a person reads it: every invisible character removed."""
    return ''.join(c for c in (text or '') if c not in INVISIBLE).strip()


def has_invisible(text):
    return any(c in INVISIBLE for c in (text or ''))


def link(branch_id, number):
    """The wa.me link the printed QR holds: the greeting, plus its signature."""
    digits = ''.join(c for c in str(number) if c.isdigit())
    return f'https://wa.me/{digits}?text={quote(GREETING + encode(branch_id))}'
