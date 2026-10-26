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
    """
    Store, push, and text only if the push reached nobody. Returns the
    notification for the order's own person.

    A business's or institution's job tells two people: the organisation's
    number, and the person who ordered it. An office line is often out of
    reach when nobody is at the desk, so the person who stood at the
    counter hears too, by the same rules.
    """
    from apps.storefront.services.accounts import leads_for

    lead = order.lead
    if lead is None:
        return None

    recipients = [lead]
    job = getattr(order, 'job', None) if getattr(order, 'job_id', None) else None
    person = getattr(job, 'ordered_by', None) if job is not None else None
    if person is not None and person.phone:
        from apps.storefront.models import Lead
        from apps.storefront.services.accounts import find_lead
        other = find_lead(person.phone) or Lead.objects.create(
            phone=person.phone, first_name=person.first_name or '', customer=person,
        )
        if other.pk not in {l.pk for l in leads_for(lead)}:
            recipients.append(other)

    first = None
    for who in recipients:
        note = _tell_one(order, who, kind, title, body, sms_text, text_with)
        first = first or note
    return first


def _tell_one(order, lead, kind, title, body, sms_text, text_with):
    """One person: store, push to their devices, text if no push arrived."""
    from apps.storefront.models import AppNotification, DeviceToken
    from apps.storefront.services import push
    from apps.storefront.services.accounts import leads_for
    from apps.storefront.services.sms import send_sms

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