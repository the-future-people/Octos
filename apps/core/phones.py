"""
Phone numbers, one rule for all of Octos.

Every number Octos keeps is in full international form (+233244123456,
+2348031234567, +15145828114): one way to write each number, so the same
person is the same number wherever they came in. Ghana is the default, so
an attendant typing 0244 123 456 gets what they expect; a number from
anywhere else is kept as that country's, never forced into a Ghanaian
shape.

Before this there were three versions of the rule (customers, the
storefront, SMS), each a little different, and they drifted: one let a
nine-digit number through; the customer search only knew Ghanaian forms,
so foreign customers were saved but could not be found. This module is
the only one now.

Built on `phonenumbers`, the library behind Android's own number handling,
which knows every country's numbering plan.
"""

import re

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

DEFAULT_REGION = 'GH'


def _parse(raw, region=DEFAULT_REGION):
    raw = (raw or '').strip()
    if not raw:
        return None
    # "00" is how many phones dial abroad; the library expects "+".
    if raw.startswith('00'):
        raw = '+' + raw[2:]
    try:
        return phonenumbers.parse(raw, region)
    except NumberParseException:
        return None


def to_international(raw, region=DEFAULT_REGION):
    """The number in international form, or None if it is not a real one."""
    parsed = _parse(raw, region)
    if parsed is None or not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)


def check(raw, region=DEFAULT_REGION):
    """
    (number, problem): the international form and None, or None and a
    plain reason for whoever typed it.
    """
    if not (raw or '').strip():
        return None, 'Enter a phone number.'
    number = to_international(raw, region)
    if number:
        return number, None

    digits = re.sub(r'\D', '', raw)
    parsed = _parse(raw, region)
    if not digits or len(digits) < 6:
        return None, "That doesn't look like a phone number."
    if not raw.strip().startswith(('+', '00')):
        # A Ghanaian shape that is the wrong length, or a foreign number
        # typed without its country code.
        if digits.startswith('0') and len(digits) == 9:
            return None, 'That number looks one digit short.'
        if digits.startswith('0') and len(digits) == 11:
            # One too many for Ghana, but exactly how many countries write
            # a mobile locally (a British 07911 123456): say both.
            return None, ('A Ghanaian number has 10 digits. If this number is from '
                          'outside Ghana, start with + and the country code '
                          '(for example +44 7911 123456).')
        return None, ('For a number outside Ghana, start with + and the '
                      'country code (for example +44 7911 123456).')
    if parsed is not None and phonenumbers.is_possible_number(parsed):
        return None, "That number isn't in use in that country. Please check it."
    return None, "That number doesn't look right. Please check it."


def display(number):
    """How a number is shown to people: Ghana's own way, others with their code."""
    parsed = _parse(number)
    if parsed is None:
        return number or ''
    if parsed.country_code == 233:
        return phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL)
    return phonenumbers.format_number(parsed, PhoneNumberFormat.INTERNATIONAL)


def is_ghanaian(number):
    parsed = _parse(number)
    return parsed is not None and parsed.country_code == 233


def lookup_forms(raw, region=DEFAULT_REGION):
    """
    Every way this number may have been stored, for searching while older
    records are still in their old forms. Once every stored number is in
    international form, the first entry alone is enough.
    """
    raw = (raw or '').strip()
    number = to_international(raw, region)
    forms = []
    if number:
        parsed = _parse(number)
        national = str(parsed.national_number)
        forms += [
            number,                                   # +233244123456
            number[1:],                               # 233244123456
            phonenumbers.format_number(parsed, PhoneNumberFormat.INTERNATIONAL),
            phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL),
        ]
        if parsed.country_code == 233:
            forms += ['0' + national, national]       # 0244123456, 244123456
    # Whatever was typed, as typed and as bare digits: an old record may
    # hold exactly that.
    forms += [raw, re.sub(r'\D', '', raw)]
    seen, out = set(), []
    for f in forms:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out