"""
Customers who sent a file from afar and went quiet (17 Nov 2026).

On 16 Nov two customers sent files from home, Octos asked what they wanted,
and neither answered. Nobody followed up, and both visits closed with
nothing. A third sent files that someone opened, then heard nothing back.

Every few minutes, while a branch is open: an open visit that isn't at the
counter, where the customer sent a file, no job has been made, and nothing
has happened for QUIET_FOR, goes to "Needs you" with the reason. Once per
visit. Octos takes it back by itself when the visit closes (handover.watch).
"""
from datetime import timedelta

from django.utils import timezone

QUIET_FOR = timedelta(minutes=30)
REASON = 'Sent a file from outside the shop and went quiet, with no job made. Worth a follow-up.'


def flag_quiet(now=None):
    """Hand every such chat to a person. Returns how many."""
    from apps.communications.assistant.counter import shop_open
    from apps.communications.models import Conversation
    from apps.communications.services import handover
    from apps.spine import kinds
    from apps.spine.models import Event, Visit
    from apps.spine.recorder import record

    now = now or timezone.now()
    if not shop_open(now):
        return 0
    visits = (Visit.objects
              .filter(closed_at__isnull=True, last_activity_at__lte=now - QUIET_FOR,
                      conversation__channel=Conversation.WHATSAPP,
                      conversation__handled_by=Conversation.OCTOS)
              .exclude(presence=Visit.AT_COUNTER)
              .exclude(conversation__status=Conversation.SPAM)
              .select_related('conversation'))
    flagged = 0
    for visit in visits:
        key = f'quiet-remote:{visit.pk}'
        if Event.objects.filter(idempotency_key=key).exists():
            continue
        if not visit.events.filter(kind=kinds.MESSAGE_RECEIVED, payload__has_file=True).exists():
            continue
        if visit.events.filter(kind__in=[kinds.JOB_CREATED, kinds.JOB_LINKED]).exists():
            continue
        chat = visit.conversation
        record(kinds.OCTOS_FLAGGED_QUIET, actor=Event.OCTOS, conversation=chat, customer=chat.customer,
               key=key, reason=REASON)
        handover.octos_hands_over(chat, REASON)
        flagged += 1
    return flagged
