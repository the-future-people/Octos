"""
Regulars (13 Nov 2026): on a 4th visit within 72 hours, Octos asks once,
warmly, whether it may save the customer's details, so they are known next
time. Rules (Khofi, 12 Nov):

  - only someone not registered with us
  - never while they are at the counter (a counter sign in the last 45 min)
  - not again within 72 hours of asking
  - not for 30 days after a "no thanks" (customer_declined_details)

Saving uses the tools Octos already has: use_phone_number and
save_customer_name. This only tells Octos when to ask.
"""
from datetime import timedelta

from django.utils import timezone

VISITS = 4
WINDOW = timedelta(hours=72)
COUNTER_RECENT = timedelta(minutes=45)
AFTER_ASKING = timedelta(hours=72)
AFTER_NO = timedelta(days=30)


def decide(registered, visits_in_window, at_counter, declined_recently, asked_recently):
    """Whether to ask now, and why not. Pure: every rule in one place."""
    if registered:
        return False, 'already registered'
    if visits_in_window < VISITS:
        return False, f'{visits_in_window} visit(s) in 72 hours'
    if at_counter:
        return False, 'at the counter'
    if declined_recently:
        return False, 'said no in the last 30 days'
    if asked_recently:
        return False, 'asked in the last 72 hours'
    return True, ''


def instruction(conversation, now=None):
    """The extra instruction for Octos, or '' when it should not ask."""
    from apps.communications.services.chat_customer import customer_for_chat
    from apps.spine import kinds
    from apps.spine.models import Event, Visit
    from apps.spine.recorder import record

    now = now or timezone.now()
    events = Event.objects.filter(conversation=conversation)
    counter_signs = (kinds.PRESENCE_COUNTER, kinds.COUNTER_CLAIMED, kinds.FILE_OPENED)
    counter_until = getattr(conversation, 'counter_until', None)
    visits = Visit.objects.filter(conversation=conversation, opened_at__gte=now - WINDOW).count()

    ask, _why = decide(
        registered=customer_for_chat(conversation) is not None,
        visits_in_window=visits,
        at_counter=bool(counter_until and counter_until > now)
                   or events.filter(kind__in=counter_signs, occurred_at__gte=now - COUNTER_RECENT).exists(),
        declined_recently=events.filter(kind=kinds.CUSTOMER_DECLINED_DETAILS, occurred_at__gte=now - AFTER_NO).exists(),
        asked_recently=events.filter(kind=kinds.OCTOS_ASKED_DETAILS, occurred_at__gte=now - AFTER_ASKING).exists(),
    )
    if not ask:
        return ''

    record(kinds.OCTOS_ASKED_DETAILS, actor=Event.OCTOS, conversation=conversation,
           key=f'asked-details:{conversation.pk}:{timezone.localtime(now).date()}',
           payload={'visits_in_72h': visits}, reason='A regular: 4th visit in 72 hours, not registered.')
    hidden = not conversation.contact_phone
    wants = 'their name and the phone number they use' if hidden else 'their name'
    return (
        f"THIS CUSTOMER IS A REGULAR: {visits} visits in the last three days, but not registered with us. "
        f"Once you have helped with what they asked, ask once, warmly and briefly, whether we may save {wants} "
        f"so we can serve them faster next time. If they share it, save it with "
        f"{'use_phone_number, then ' if hidden else ''}save_customer_name. If they say no, accept it kindly, "
        f"call customer_declined_details, and do not ask again. If they ignore the question, let it go."
    )
