"""
A counter job finds its WhatsApp chat, by phone number (Layer 2, Step 2.4a, 11 Nov 2026).

When a job is made for a customer whose number (phone or secondary_phone) is
the number of a chat with an open visit, active in the last WITHIN, they are
the same person, standing at the counter. The job is linked to that chat (the
same conversation.jobs link the inbox's link-job uses), so the visit closes as
JOB_CREATED, its files are handled, and the inbox shows the job card. No click.

Numbers are compared in one form, through the shop's one normaliser
(storefront.services.accounts.normalise_phone): 0244... and +233244... agree.
"""
from datetime import timedelta

from django.utils import timezone

WITHIN = timedelta(hours=2)


def phones_of(customer):
    """The customer's numbers, normalised, without blanks or repeats."""
    from apps.storefront.services.accounts import normalise_phone
    found = []
    for raw in (getattr(customer, 'phone', ''), getattr(customer, 'secondary_phone', '')):
        normal = normalise_phone(raw or '') if raw else None
        if normal and normal not in found:
            found.append(normal)
    return found


def chat_for(customer, now=None):
    """The chat with an open, recent visit for this customer's number, or None."""
    from apps.communications.models import Conversation
    from apps.spine.models import Visit
    if customer is None:
        return None
    phones = phones_of(customer)
    if not phones:
        return None
    now = now or timezone.now()
    visit = (Visit.objects.select_related('conversation')
             .filter(closed_at__isnull=True, last_activity_at__gte=now - WITHIN,
                     conversation__contact_phone__in=phones,
                     conversation__channel=Conversation.WHATSAPP)
             .order_by('-last_activity_at').first())
    return visit.conversation if visit else None


def link_new_job(job, now=None):
    """Link a new job to its customer's open chat. Returns the chat, or None."""
    conversation = chat_for(getattr(job, 'customer', None), now)
    if conversation is not None:
        conversation.jobs.add(job)
    return conversation
