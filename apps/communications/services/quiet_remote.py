"""
Customers who sent a file from afar and went quiet (17 Nov 2026).

On 16 Nov two customers sent files from home, Octos asked what they wanted,
and neither answered. Nobody followed up, and both visits closed with
nothing. A third sent files that someone opened, then heard nothing back.

Every few minutes, while a branch is open: an open visit that isn't at the
counter, where the customer sent a file, no job has been made and no receipt
sent, and nothing has happened for QUIET_FOR, goes to "Needs you" with the reason. Once per
visit. Octos takes it back by itself when the visit closes (handover.watch).

20 Nov 2026, from a week of chats:
- A job made or a receipt sent for the chat earlier the same day counts too:
  Osekre's job was made and his receipt sent, then a corrected copy of the
  same file opened a new visit and was flagged as "no job made".
- Octos follows up once himself first, and a person is brought in only if
  that gets no answer either. Noel and Dominic were handed to staff without
  a word to them, and nobody wrote.
- Before that, Octos reads the chat for proof the team already dealt with it
  (settled.py): a person wrote or sent a file back, a job, a receipt, a
  payment. Then it stays out. And the follow-up is written from the chat,
  like a teammate who knows it, never a stock "just checking in": if the
  chat shows nothing is open, Octos says nothing and nobody is called.
"""
from datetime import timedelta

from django.utils import timezone

QUIET_FOR = timedelta(minutes=30)
REASON = 'Sent a file from outside the shop and went quiet, with no job made. Worth a follow-up.'


def dealt_with(chat, visit):
    """
    The visit's work is done: a job made or linked (as an event, or a job
    attached to the chat since the visit began, however it was attached), or
    a receipt sent. On 17 Nov 2026 Cassy was flagged though her job was made
    and her receipt sent: the job had been attached by hand, with no event.
    """
    from apps.spine import kinds

    if visit.events.filter(kind__in=[kinds.JOB_CREATED, kinds.JOB_LINKED]).exists():
        return True
    since = min(visit.opened_at, _start_of_day(visit.opened_at))
    if chat.jobs.filter(created_at__gte=since).exists():
        return True
    if chat.customer_id and chat.customer.jobs.filter(created_at__gte=since).exists():
        return True
    if chat.messages.filter(kind='receipt', created_at__gte=since).exists():
        return True
    from apps.communications.services.settled import team_dealt_with
    return bool(team_dealt_with(chat, visit.opened_at))


def _start_of_day(moment):
    local = timezone.localtime(moment)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _follow_up(chat, visit, now):
    """
    Octos follows up once, in his own words from the chat (brain.follow_up).
    Returns 'said', 'nothing' (the chat needed nothing: nobody is called) or
    '' when he couldn't (off, window closed, an error): then a person is.
    """
    from apps.communications.assistant import brain
    from apps.communications.models import AssistantRun
    from apps.communications.services.window import window_open
    from apps.spine import kinds
    from apps.spine.models import Event
    from apps.spine.recorder import record
    if not window_open(chat):
        return ''
    run = brain.follow_up(chat.pk, now)
    if run is None or run.decision == AssistantRun.FAILED or run.reason == 'follow-up: could not verify it':
        return ''
    said = run.decision in (AssistantRun.REPLIED, AssistantRun.SHADOWED)
    if not said and run.reason != brain.FOLLOW_UP_NOTHING:
        return ''
    record(kinds.OCTOS_FOLLOWED_UP, actor=Event.OCTOS, conversation=chat, customer=chat.customer,
           key=f'quiet-follow-up:{visit.pk}', occurred_at=now, payload={'said': said, 'run_id': run.pk},
           reason=('Sent a file from outside the shop and went quiet: Octos followed up once.' if said
                   else 'Octos read the chat after the customer went quiet: nothing was left open.'))
    return 'said' if said else 'nothing'


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
        chat = visit.conversation
        if dealt_with(chat, visit):
            continue
        # Octos follows up first; the visit's quiet clock restarts from his message.
        followed = Event.objects.filter(idempotency_key=f'quiet-follow-up:{visit.pk}').first()
        if followed is None:
            if _follow_up(chat, visit, now):
                continue
        elif followed.payload.get('said') is False:
            continue                         # he read the chat: nothing was open
        record(kinds.OCTOS_FLAGGED_QUIET, actor=Event.OCTOS, conversation=chat, customer=chat.customer,
               key=key, reason=REASON)
        handover.octos_hands_over(chat, REASON)
        flagged += 1
    return flagged
