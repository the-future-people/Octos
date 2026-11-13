"""
Octos as a system actor (moved here 13 Nov 2026 from
apps/communications/assistant/proformas.py).

Automatic actions are signed by Octos's own account rather than left blank,
so every record says who did it. The account is created by
`python manage.py setup_octos`: role OCTOS, no password, never active.

It lives in accounts because it is an account. Finance (the attendant's
automatic sign-off) and communications (proformas) both use it, and neither
should have to import the other to find it.
"""

OCTOS_ROLE = 'OCTOS'


def octos_user():
    """The account Octos acts as, or None if setup_octos has not been run."""
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(role__name=OCTOS_ROLE).first()


def require_octos_user():
    """
    The Octos account, or a loud failure.

    For actions that must be signed: writing a blank signer would hide a
    missing system account until someone went looking for it.
    """
    user = octos_user()
    if user is None:
        raise RuntimeError(
            'The Octos system account is missing. Run: python manage.py setup_octos'
        )
    return user
