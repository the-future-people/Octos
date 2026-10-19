"""
Telling a customer something about their order.

App first: the message goes to the inbox, and by push to every phone
signed in to their number. If no phone could be reached (no app, signed
out, notifications turned off, or Firebase not set up), the same news
goes by SMS, as it always has. Website customers have no app, so for
them nothing changes.
"""

import logging

logger = logging.getLogger(__name__)


def tell(order, kind, title, body, sms_text=None, text_with=None):
    """Store, push, and text only if the push reached nobody. Returns the notification."""
    from apps.storefront.models import AppNotification, DeviceToken
    from apps.storefront.services import push
    from apps.storefront.services.accounts import leads_for
    from apps.storefront.services.sms import send_sms

    lead = order.lead
    if lead is None:
        return None

    note = AppNotification.objects.create(
        lead=lead, order=order, kind=kind, title=title, body=body,
    )

    devices = DeviceToken.objects.filter(
        session__lead__in=leads_for(lead), session__revoked_at__isnull=True,
    )
    data = {'kind': kind, 'order': order.order_number, 'token': order.access_token}
    for device in devices:
        try:
            if push.send(device.token, title, body, data):
                note.pushed = True
        except push.TokenGone:
            device.delete()
        except Exception:
            logger.exception('Could not push %s about %s', kind, order.order_number)

    if not note.pushed and sms_text:
        try:
            # The caller's own send_sms where given, so the places that
            # always texted (and their tests) keep their texter.
            (text_with or send_sms)(lead.phone, sms_text)
            note.texted = True
        except Exception:
            logger.exception('Could not text %s about %s', lead.phone, order.order_number)

    note.save(update_fields=['pushed', 'texted'])
    return note



def ready_phrase(order):
    """'ready about 3:40 pm today' from the promise, or nothing."""
    from django.utils import timezone
    if not order.promised_for:
        return ''
    at = timezone.localtime(order.promised_for)
    day = 'today' if at.date() == timezone.localdate() else at.strftime('%A')
    return f'Ready about {at.strftime("%I:%M %p").lstrip("0").lower()} {day}.'