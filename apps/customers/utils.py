# apps/customers/utils.py
import re

from apps.core.phones import lookup_forms, to_international


def normalise_phone(phone: str) -> str:
    """
    The one stored form, international (+233244123456, +15145828114),
    through the phone rule for all of Octos. Every stored number has been
    converted to it, so new ones match the old exactly.

    Returns the original string unchanged if it is not a real number, so
    the caller can decide, as before.
    """
    if not phone:
        return phone
    return to_international(phone) or phone.strip()

def phone_variants(phone: str) -> list[str]:
    """Every form this number may be stored in, Ghanaian or not."""
    return lookup_forms(phone)