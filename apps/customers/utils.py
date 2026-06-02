# apps/customers/utils.py
import re


def normalise_phone(phone: str) -> str:
    """
    Normalises a Ghana phone number to the canonical 0XXXXXXXXX (10-digit) format.

    Handles:
        +233XXXXXXXXX  → 0XXXXXXXXX
        233XXXXXXXXX   → 0XXXXXXXXX
        0XXXXXXXXX     → 0XXXXXXXXX  (already canonical)
        spaces / dashes / brackets / dots → stripped before processing

    Returns the original string unchanged if it cannot be normalised
    (too short, non-numeric after stripping) — fail-open so we never
    silently discard a phone the user actually typed.
    """
    if not phone:
        return phone

    # Strip all non-digit characters except leading +
    cleaned = re.sub(r'[\s\-().]+', '', phone.strip())

    if cleaned.startswith('+233'):
        cleaned = '0' + cleaned[4:]
    elif cleaned.startswith('233') and len(cleaned) >= 12:
        cleaned = '0' + cleaned[3:]

    # Validate: must be 10 digits starting with 0
    if re.fullmatch(r'0\d{9}', cleaned):
        return cleaned

    # Cannot normalise — return original so the caller can decide
    return phone.strip()


def phone_variants(phone: str) -> list[str]:
    """
    Returns all known format variants of a phone number so that a
    __in query matches records stored in any historical format.

    Example: '0244123456' → ['0244123456', '+233244123456', '233244123456']
    """
    canonical = normalise_phone(phone)

    # If normalisation failed (returned original non-canonical), just return as-is
    if not re.fullmatch(r'0\d{9}', canonical):
        return [phone.strip()]

    local    = canonical                    # 0244123456
    intl     = '+233' + canonical[1:]       # +233244123456
    intl_raw = '233'  + canonical[1:]       # 233244123456

    return [local, intl, intl_raw]