"""
When Octos speaks, and when it waits (6 Nov 2026).

The quiet window: Octos replies once the customer has gone quiet, as a
person at the counter waits for everything to load before asking. After
words, a short wait. After a file, or a message with no words ("." before
a file), longer: 45 seconds, or 2 minutes while a branch is open (the
customer may be at the counter). Every new message starts its own wait and
only the latest one's run answers, so a stream of 30 photos gets one reply.

Counter visits, during opening hours: the QR code's message ("Hi, I'm at
the Westland counter"), "I'm here" and the like, or the attendant's "At the
counter" tap. One line of acknowledgement, then silence for 30 minutes
after the customer's last message. A visit is temporary, never a label:
remember the person, never assume their intent from their history.

A file with no words while open gets one message suiting both cases. And
once Octos has acknowledged a batch of files, more files with no words get
silence until the customer writes.
"""
import re
from datetime import timedelta

from django.utils import timezone

from apps.communications.models import Message

WORDS_WAIT = 8        # seconds after words
CLOSED_WAIT = 45      # after a file or no words, branches closed
OPEN_WAIT = 120       # after a file or no words, a branch open (the counter)
VISIT = timedelta(minutes=30)
FORK_WINDOW = timedelta(minutes=30)
FORK_REASON = 'file only: asked once'
FORK_TEXT = ("Got your file \U0001F44D If you're at the counter, the attendant will pick it up. "
             "If not, just tell me what you'd like printed and I'll price it for you.")
MEDIA = (Message.IMAGE, Message.DOCUMENT, Message.VIDEO)
QR = re.compile(r"\bi(?:'|\u2019)?m at the ([a-z][a-z ]*?) counter\b")
HERE = re.compile(r"\b(?:i(?:'|\u2019)?m|i am)\s+(?:here|at the (?:shop|counter|desk|front desk)|in the shop)\b"
                  r"|\bat the counter\b")
GREY = {'l', '1', 'la', 'gray', 'grey', 'grayscale', 'greyscale', 'bw', 'black and white'}


ATTENDED_KEY = 'octos:counter-attended'
ATTENDED_WITHIN = timedelta(minutes=5)
AFTER_CLOSING = timedelta(hours=3)


def mark_attended(now=None):
    """An attendant's screen is open right now (the Claim strip's poll is the heartbeat)."""
    from django.core.cache import cache
    cache.set(ATTENDED_KEY, (now or timezone.now()).timestamp(), timeout=3600)


def attended(now=None):
    """Someone has had the attendant portal open in the last 5 minutes."""
    from django.core.cache import cache
    seen = cache.get(ATTENDED_KEY)
    return bool(seen) and (now or timezone.now()).timestamp() - seen <= ATTENDED_WITHIN.total_seconds()


def shop_open(now=None):
    """
    Someone is at a counter Octos speaks for. During opening hours, yes. After
    closing, only while an attendant's screen is alive, and for at most 3
    hours past closing (11 Nov 2026: customers were served at 19:40, after the
    timetable said closed, and Octos treated them as away).
    """
    from apps.organization.models import Branch
    from apps.organization.services import hours
    now = now or timezone.now()
    branches = list(Branch.objects.filter(is_trading=True, is_active=True))
    if any(hours.is_open(b, now) for b in branches):
        return True
    return attended(now) and any(_just_closed(b, now) for b in branches)


def _just_closed(branch, now):
    """Within AFTER_CLOSING of this branch's closing time today."""
    from apps.organization.services import hours
    local = timezone.localtime(now)
    try:
        closes = hours.hours_on(branch, local.date())[1]
    except Exception:
        return False
    if not closes:
        return False
    closing = local.replace(hour=closes.hour, minute=closes.minute, second=0, microsecond=0)
    return closing <= local <= closing + AFTER_CLOSING


def has_words(text):
    """Any letter or digit, in any language. '.', '?' and emoji are not words."""
    return bool(re.search(r'[^\W_]', text or ''))


def no_words(message):
    """A customer's message with nothing to read: a file without a caption, '.', an emoji."""
    if message.direction != Message.INBOUND:
        return False
    body = (message.body or '').strip()
    if message.message_type in MEDIA:
        return not body or body == (message.media_name or '').strip() or not has_words(body)
    return not has_words(body)


def file_only(message):
    return message.message_type in MEDIA and no_words(message)


def quiet_window(message, now=None):
    """Seconds to wait after this message for the customer to go quiet."""
    if not no_words(message) and not expects_file(message):
        return WORDS_WAIT
    return OPEN_WAIT if shop_open(now) else CLOSED_WAIT


def counter_phrase(text):
    """The branch a counter message names ('westland'), '' for one naming none, None for no counter message."""
    lowered = (text or '').lower()
    named = QR.search(lowered)
    if named:
        return named.group(1).strip()
    return '' if HERE.search(lowered) else None


def in_visit(conversation, now=None):
    until = getattr(conversation, 'counter_until', None)
    return bool(until and until > (now or timezone.now()))


def arrived(conversation, message, now=None):
    """
    The moment a customer's message arrives: proof or a phrase that they are
    at the counter starts the visit now, not when Octos's run gets to it.

    The printed QR's invisible signature (assistant/qr.py, 11 Nov 2026) is
    proof of the branch, at any hour. Without it, a counter phrase during
    opening hours still counts, as before. Returns True when a visit started.
    """
    from apps.communications.assistant import qr
    now = now or timezone.now()
    if message.direction != Message.INBOUND:
        return False

    if qr.has_invisible(message.body):
        branch_id, verified = qr.decode(message.body)
        # Stored as people read it: the proof lives on the spine, not in the text.
        plain = qr.clean(message.body)
        Message.objects.filter(pk=message.pk).update(body=plain)
        message.body = plain
        if verified:
            from apps.organization.models import Branch
            branch = Branch.objects.filter(pk=branch_id).first()
            _visit(conversation, branch, now)
            _record_presence(conversation, message, branch, verified=True, how='signed QR')
            return True
        if branch_id is not None:
            import logging
            logging.getLogger(__name__).warning(
                'Counter QR signature failed its check on message %s', message.pk)

    if not shop_open(now):
        return False
    named = counter_phrase(message.body)
    if named is None:
        return False
    branch = _branch(named)
    _visit(conversation, branch, now)
    _record_presence(conversation, message, branch, verified=False, how=named or 'here')
    return True


def _record_presence(conversation, message, branch, verified, how):
    from apps.spine import kinds
    from apps.spine.models import Event
    from apps.spine.recorder import record
    record(kinds.PRESENCE_COUNTER, actor=Event.CUSTOMER, conversation=conversation,
           customer=conversation.customer, branch=branch, key=f'presence:{message.pk}',
           payload={'message_id': message.pk, 'verified': verified, 'how': how},
           reason=('Scanned the counter QR' if verified else 'Said they are at the counter')
                  + (f' at {branch.name}.' if branch else '.'))


def _verified_qr(message):
    """The branch whose signed QR this message came from, or None."""
    from apps.spine import kinds
    from apps.spine.models import Event
    event = (Event.objects.select_related('branch')
             .filter(kind=kinds.PRESENCE_COUNTER, payload__message_id=message.pk,
                     payload__verified=True).first())
    return event.branch if event else None

def is_grey(mode):
    return str(mode).strip().lower() in GREY


def start_visit(conversation, branch=None, now=None):
    """A counter visit (the QR message, 'I'm here', or the attendant's tap)."""
    _visit(conversation, branch or _branch(''), now or timezone.now())


def step(conversation, trigger, now):
    """
    What these rules say for this message: (text to send or None, reason),
    or None when they have nothing to say and Octos answers as usual.
    """
    if trigger is None:
        return None
    # The signed QR: proof of the branch, acknowledged like the counter phrase.
    signed_at = _verified_qr(trigger)
    if signed_at is not None:
        _visit(conversation, signed_at, now)
        return ack_text(conversation, signed_at), 'counter visit started'
    opened = shop_open(now)
    if opened:
        named = counter_phrase(trigger.body)
        if named is not None:
            branch = _branch(named)
            _visit(conversation, branch, now)
            return ack_text(conversation, branch), 'counter visit started'
    # Where is the customer? A belief, not a timer (Layer 2, Step 2.2).
    from apps.spine import presence
    belief = presence.for_message(conversation, trigger, now, opened)
    if belief.band == presence.AT_COUNTER:
        if in_visit(conversation, now):
            _visit(conversation, None, now)        # keeps the inbox's counter strip fresh
        return None, f'at the counter, the attendant has them ({belief.why})'
    if belief.band == presence.UNSURE:
        if belief.texture in ('words', 'info_question', 'status_question', 'on_the_way'):
            held = _hold(conversation, trigger, belief)
            if held:
                return None, held
        elif belief.texture == 'greeting' and opened:
            if not _greeted_unsure(conversation, now):
                return NOT_SURE_GREETING, NOT_SURE_REASON
            return None, 'not sure where they are: greeted already, waiting for their words'
    if no_words(trigger) and _batch_acknowledged(conversation, trigger):
        return None, 'files already acknowledged: waiting for their words'
    if opened and file_only(trigger):
        from apps.communications.models import AssistantRun
        asked = AssistantRun.objects.filter(conversation=conversation, reason=FORK_REASON,
                                            created_at__gte=now - FORK_WINDOW).exists()
        if asked:
            return None, 'file only: already asked, waiting for their words'
        return FORK_TEXT, FORK_REASON
    return None


NOT_SURE_REASON = 'greeted: not sure where they are'
NOT_SURE_GREETING = ("Hi \U0001F44B Welcome to Farhat. If you're at the counter, hand your files to the "
                     "attendant. If not, just tell me what you'd like printed and I'll help you.")
HOLD_REASON = 'held for the attendant'
HOLD_SECONDS = 120


def _greeted_unsure(conversation, now):
    from apps.communications.models import AssistantRun
    return AssistantRun.objects.filter(conversation=conversation, reason=NOT_SURE_REASON,
                                       created_at__gte=now - FORK_WINDOW).exists()


def _hold(conversation, trigger, belief):
    """
    Not sure they've left, and they asked something: the attendant gets the
    first chance. The attendant is alerted, and this same message is looked at
    again in 2 minutes; if nobody has answered by then, Octos does. Returns the
    reason when holding, or None when this message was already held once.
    """
    from django.db import transaction
    from apps.communications.models import AssistantRun
    if AssistantRun.objects.filter(conversation=conversation, trigger=trigger,
                                   reason__startswith=HOLD_REASON).exists():
        return None
    from apps.communications.tasks import answer_whatsapp
    transaction.on_commit(
        lambda: answer_whatsapp.apply_async((conversation.pk, trigger.pk), countdown=HOLD_SECONDS))
    from apps.communications.services.handover import _alert
    _alert(conversation, verb='customer_waiting',
           message=f'{conversation.display_name} may be at the counter: "{(trigger.body or "")[:60]}". '
                   f'Octos answers in 2 minutes if nobody does.')
    return f'{HOLD_REASON}: not sure where they are ({belief.why})'


def ack_text(conversation, branch):
    """
    The one acknowledgement at the counter (11 Nov 2026): warm, personal when
    Octos truly knows the name, never the customer's phone digits.
    """
    name = (branch.name or '') if branch is not None else ''
    where = name[:-7] if name.endswith(' Branch') else name
    first = _first_name(conversation)
    hello = f'Hi {first} \U0001F44B' if first else 'Hi \U0001F44B'
    shop = f'Farhat {where}' if where else 'Farhat'
    return (f"{hello} Welcome to {shop}. Hand your files to the attendant, "
            f"or drop them here and they'll pick them up.")


def _first_name(conversation):
    """
    A registered customer's first name, from their customer record only.
    Never the WhatsApp profile name: "PEOPLE'S KOFI" is how "Hi People's"
    happened. A name we can't trust is worse than no name.
    """
    customer = getattr(conversation, 'customer', None)
    if customer is None:
        return ''
    for field in ('first_name', 'full_name', 'name'):
        value = (getattr(customer, field, '') or '').strip()
        if value:
            return value.split()[0].title()
    return ''


def _batch_acknowledged(conversation, trigger):
    """
    Octos last spoke having seen files with no words, and since then the
    customer has only sent more of the same: wait for their words.

    Only a reply written with the files in view counts: one from a run
    that started after they arrived. A reply that merely crossed them
    ("The file didn't come through", written while the PDF was still
    uploading) does not (James, 6 Nov 2026).
    """
    from apps.communications.models import AssistantRun
    earlier = list(conversation.messages.filter(is_internal_note=False, created_at__lt=trigger.created_at)
                   .order_by('-created_at')[:80])
    i = 0
    while i < len(earlier) and earlier[i].direction == Message.INBOUND:
        if not no_words(earlier[i]):
            return False
        i += 1
    if i == len(earlier) or earlier[i].sent_by_id is not None:
        return False
    files = []
    j = i + 1
    while j < len(earlier) and earlier[j].direction == Message.INBOUND and no_words(earlier[j]):
        if earlier[j].message_type in MEDIA:
            files.append(earlier[j])
        j += 1
    if not files:
        return False
    return AssistantRun.objects.filter(
        conversation=conversation, decision__in=[AssistantRun.REPLIED, AssistantRun.SHADOWED],
        trigger__created_at__gte=min(f.created_at for f in files),
        trigger__created_at__lte=earlier[i].created_at).exists()


def _branch(named):
    from apps.organization.models import Branch
    if named:
        for branch in Branch.objects.filter(is_active=True):
            if named in (branch.name or '').lower():
                return branch
    return Branch.objects.filter(is_trading=True, is_active=True).first()


def _visit(conversation, branch, now):
    from apps.communications.models import Conversation
    fields = {'counter_until': now + VISIT}
    if branch is not None:
        fields['counter_branch'] = branch
    Conversation.objects.filter(pk=conversation.pk).update(**fields)
    for key, value in fields.items():
        setattr(conversation, key, value)


# Words that point to a file ("3 copies of this file") while it is still
# uploading: wait for it, as for a file (James, 6 Nov 2026).
MENTIONS_FILE = re.compile(r"\b(this|these|attached|attachment|files?|documents?|docs?|pdfs?|pictures?"
                           r"|photos?|images?|flyers?|cv)\b", re.IGNORECASE)


def expects_file(message):
    """Words promising a file that hasn't arrived in the last 10 minutes."""
    if message.direction != Message.INBOUND or message.message_type in MEDIA:
        return False
    if not MENTIONS_FILE.search(message.body or ''):
        return False
    since = message.created_at - timedelta(minutes=10)
    return not message.conversation.messages.filter(
        direction=Message.INBOUND, message_type__in=MEDIA,
        created_at__gte=since, created_at__lte=message.created_at).exists()
