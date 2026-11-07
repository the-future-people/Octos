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
FORK_TEXT = ("Got your file. If you're at the counter, the attendant will take it from here. "
             "If not, just tell me what you'd like printed.")
MEDIA = (Message.IMAGE, Message.DOCUMENT, Message.VIDEO)
QR = re.compile(r"\bi(?:'|\u2019)?m at the ([a-z][a-z ]*?) counter\b")
HERE = re.compile(r"\b(?:i(?:'|\u2019)?m|i am)\s+(?:here|at the (?:shop|counter|desk|front desk)|in the shop)\b"
                  r"|\bat the counter\b")
GREY = {'l', '1', 'la', 'gray', 'grey', 'grayscale', 'greyscale', 'bw', 'black and white'}


def shop_open(now=None):
    """A branch Octos speaks for is open right now."""
    from apps.organization.models import Branch
    from apps.organization.services import hours
    return any(hours.is_open(b, now) for b in Branch.objects.filter(is_trading=True, is_active=True))


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
    opened = shop_open(now)
    if opened:
        named = counter_phrase(trigger.body)
        if named is not None:
            branch = _branch(named)
            _visit(conversation, branch, now)
            return ack_text(conversation, branch), 'counter visit started'
        if in_visit(conversation, now):
            _visit(conversation, None, now)
            return None, 'counter visit: the attendant has this customer'
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


def ack_text(conversation, branch):
    name = (branch.name or '') if branch is not None else ''
    where = name[:-7] if name.endswith(' Branch') else (name or 'the shop')
    digits = ''.join(c for c in (conversation.contact_phone or '') if c.isdigit())[-2:]
    tail = f' Your number ends in {digits}.' if digits else ''
    return f'Got it. The attendant at {where} will take it from here.{tail}'


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
