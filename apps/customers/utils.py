# apps/customers/utils.py
import re

from apps.core.phones import lookup_forms, to_international


def normalise_phone(phone: str) -> str:
    """
    The customers' stored form, through the one phone rule for all of
    Octos (apps.core.phones). Ghanaian numbers are kept as 0XXXXXXXXX for
    now, because that is how every customer is stored until the stored
    numbers are converted to international form; foreign numbers are kept
    in their international form (+15145828114), checked rather than
    taken as typed.

    Returns the original string unchanged if it is not a real number, so
    the caller can decide, as before.
    """
    if not phone:
        return phone
    number = to_international(phone)
    if number is None:
        return phone.strip()
    if number.startswith('+233'):
        return '0' + number[4:]
    return number


def phone_variants(phone: str) -> list[str]:
    """Every form this number may be stored in, Ghanaian or not."""
    return lookup_forms(phone)