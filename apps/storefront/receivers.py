"""
The welcome for an account made in the app: queued once the sign-up has
saved, and sent by the worker so nobody waits on it.

Customers registered by staff no longer get a welcome (14 Nov 2026):
"Welcome to Farhat Printing Press!" arrived while they were still at the
counter, mid-job. They're thanked at the end of the day instead
(storefront/services/thanks).

Not sent when the WELCOME_TEXTS setting is False, or during a test run.
"""

from django.conf import settings
from django.db import transaction


def queue_greeting(phone, name=''):
    """
    The welcome for an account made in the app. Called by verify_code once
    a new lead is created; sent after the sign-up has saved, by the worker.
    """
    if not getattr(settings, 'WELCOME_TEXTS', True):
        return
    transaction.on_commit(lambda: _queue_greeting(phone, name))


def _queue_greeting(phone, name):
    # A test run never texts real people, whatever key the environment holds.
    import sys
    if 'test' in sys.argv and not getattr(settings, 'WELCOME_IN_TESTS', False):
        return
    try:
        from apps.storefront.tasks import send_greeting
        send_greeting.delay(phone, name)
    except Exception:
        # No worker reachable: send it here rather than not at all.
        from apps.storefront.services.welcome import greet
        greet(phone, name)
