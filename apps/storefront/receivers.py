"""
What happens when a customer is registered: the welcome is queued once
the registration has saved, and sent by the worker so nobody waits on it.

Not fired for bulk loads (bulk_create sends no signal), for fixtures
(raw), for walk-ins, for an instance marked _skip_welcome, or when the
WELCOME_TEXTS setting is False.
"""

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='customers.CustomerProfile', dispatch_uid='storefront-welcome-new-customer')
def welcome_new_customer(sender, instance, created, raw=False, **kwargs):
    if not created or raw:
        return
    if getattr(instance, '_skip_welcome', False) or instance.is_walkin:
        return
    if not getattr(settings, 'WELCOME_TEXTS', True):
        return
    pk = instance.pk
    transaction.on_commit(lambda: _queue(pk))


def _queue(customer_id):
    # A test run never texts real people, whatever key the environment holds.
    import sys
    if 'test' in sys.argv and not getattr(settings, 'WELCOME_IN_TESTS', False):
        return
    try:
        from apps.storefront.tasks import send_welcome
        send_welcome.delay(customer_id)
    except Exception:
        # No worker reachable: send it here rather than not at all.
        from apps.storefront.services.welcome import welcome
        welcome(customer_id)
