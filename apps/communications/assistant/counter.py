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
GREETING_WAIT = 20    # after a bare "Hi": a file often follows (14 Nov 2026)
CLOSED_WAIT = 45      # after a file or no words, branches closed
OPEN_WAIT = 120       # after a file or no words, a branch open (the counter)
VISIT = timedelta(minutes=30)
FORK_WINDOW = timedelta(minutes=30)
FORK_REASON = 'file only: asked once'
# One plain question (14 Nov 2026): no "if you're at the counter" lines.
FORK_TEXT = "Got your file \U0001F44D What would you like done with it?"
MEDIA = (Message.IMAGE, Message.DOCUMENT, Message.VIDEO)
VOICE_REASON = 'voice note: asked them to type it'
VOICE_TEXT = "Sorry, I can't listen to voice notes yet \U0001F64F Could you type it for me?"
QR = re.compile(r"\bi(?:'|\u2019)?m at the ([a-z][a-z ]*?) counter\b")
HERE = re.compile(r"\b(?:i(?:'|\u2019)?m|i am)\s+(?:here|at the (?:shop|counter|desk|front desk)|in the shop)\b"
                  r"|\bat the counter\b")
GREY = {'l', '1', 'la', 'gray', 'grey', 'grayscale', 'greyscale', 'bw', 'black and white'}


def shop_open(now=None):
    """
    Someone is at a counter Octos speaks for: open, or closing up (past closing
    time, a cashier not yet signed off). One rule, in one place:
    organization/services/shop_state (11 Nov 2026).
    """
    from apps.organization.services import shop_state
    return shop_state.any_branch(now) in (shop_state.OPEN, shop_state.CLOSING)


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


def bare_greeting(message):
    """'Hi', 'hello', 'good morning' and nothing else: a file often follows."""
    from apps.spine.presence import GREETING
    return (message.direction == Message.INBOUND and message.message_type == Message.TEXT
            and bool(GREETING.match((message.body or '').strip())))


def quiet_window(message, now=None):
    """Seconds to wait after this message for the customer to go quiet."""
    # "Hi" then a file is the commonest opening: give the file a moment to
    # land, so the two get one reply. The signed QR is acknowledged at once.
    if bare_greeting(message) and _verified_qr(message) is None:
        return GREETING_WAIT
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
            # The QR proves which branch, not that anyone is at its counter:
            # a poster or a saved photo of it can be scanned at home. Only
            # while the shop is open does it start a visit (Clarity, 14 Nov
            # 2026: the counter greeting at 9:24pm, then silence).
            if not shop_open(now):
                return False
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
    # The signed QR: proof of the branch, acknowledged like the counter phrase,
    # and only while the shop is open (see arrived()).
    opened = shop_open(now)
    signed_at = _verified_qr(trigger) if opened else None
    if signed_at is not None:
        _visit(conversation, signed_at, now)
        return ack_text(conversation, signed_at, now), ACK_REASON
    if opened:
        named = counter_phrase(trigger.body)
        if named is not None:
            branch = _branch(named)
            _visit(conversation, branch, now)
            return ack_text(conversation, branch, now), ACK_REASON
    # Someone at Farhat has this chat open right now: a greeting or a file is
    # theirs to pick up, so Octos stays quiet (14 Nov 2026). Questions with
    # words still go on, so nobody is left unanswered by a chat left open.
    from apps.communications.services.opened import in_focus
    # Only while the shop is open (15 Nov 2026): out of hours, whoever has
    # the chat open is keeping an eye on it, not serving. Octos answers.
    from apps.communications.assistant.brain import taken_back_since
    if opened and (bare_greeting(trigger) or no_words(trigger)) and in_focus(conversation.pk) \
            and not taken_back_since(conversation, trigger):
        return None, 'a person has this chat open'
    # Where is the customer? A belief, not a timer (Layer 2, Step 2.2).
    from apps.spine import presence
    belief = presence.for_message(conversation, trigger, now, opened)
    if belief.band == presence.AT_COUNTER:
        if in_visit(conversation, now):
            _visit(conversation, None, now)        # keeps the inbox's counter strip fresh
        return None, f'at the counter, the attendant has them ({belief.why})'
    # A voice note (20 Nov 2026): Octos can't listen yet, so it asks them to
    # type it, once a visit. Listening comes later, as its own piece of work.
    if trigger.message_type == Message.AUDIO:
        from apps.communications.models import AssistantRun
        from apps.spine.visits import QUIET_GAP
        if AssistantRun.objects.filter(conversation=conversation, reason=VOICE_REASON,
                                       created_at__gte=now - QUIET_GAP).exists():
            return None, 'voice note: asked them to type already'
        return VOICE_TEXT, VOICE_REASON
    if belief.band == presence.UNSURE:
        if belief.texture in ('words', 'info_question', 'status_question', 'on_the_way'):
            held = _hold(conversation, trigger, belief)
            if held:
                return None, held
            # Two minutes on: if the attendant dealt with it meanwhile, Octos
            # stays out. Adodo's job was made a second before Octos asked
            # her to send her files again (24 Nov 2026).
            from apps.communications.services.settled import team_dealt_with
            done = team_dealt_with(conversation, trigger.created_at)
            if done:
                return None, f'held for the attendant, who dealt with it: {done}'
        elif belief.texture == 'greeting' and opened:
            if not _greeted_unsure(conversation, now):
                return unsure_greeting(conversation, trigger, now), NOT_SURE_REASON
            return None, 'not sure where they are: greeted already, waiting for their words'
    # Taken back from a person who never wrote (20 Nov 2026): if anything not
    # from the customer shows the team dealt with it (a reply, a file sent
    # back, a job, a receipt, a payment), Octos stays quiet. Otherwise it
    # answers with the whole chat in view, as part of the team: never the
    # stock "what would you like done?" and never a canned check-in.
    if taken_back_since(conversation, trigger):
        from apps.communications.services.settled import team_dealt_with
        done = team_dealt_with(conversation, trigger.created_at)
        if done:
            return None, f'taken back, but the team dealt with it: {done}'
        return None
    if no_words(trigger) and _batch_acknowledged(conversation, trigger):
        return None, 'files already acknowledged: waiting for their words'
    if file_only(trigger):
        from apps.communications.models import AssistantRun
        asked = AssistantRun.objects.filter(conversation=conversation, reason=FORK_REASON,
                                            created_at__gte=now - FORK_WINDOW).exists()
        if asked:
            return None, 'file only: already asked, waiting for their words'
        # The greeting no longer says where files go (14 Nov 2026), so a file
        # after it gets its own short question.
        # They said what it's for just before ("use this one instead"): Octos
        # answers with the conversation in view, not the stock question.
        if _words_before(conversation, trigger, now):
            return None
        # Closed (17 Nov 2026): a file sent after hours got no word at all.
        # Say when we open, and still ask what it's for.
        if not opened:
            # Only when they've said nothing lately: words earlier ("3 copies
            # of this file") mean Octos answers with them in view.
            if _words_before(conversation, trigger, now, within=timedelta(minutes=30), anywhere=True):
                return None
            return closed_fork_text(now), FORK_REASON
        return FORK_TEXT, FORK_REASON
    return None


def closed_fork_text(now):
    """'Got your file. We're closed now and open again at 8:00am tomorrow. What would you like done with it?'"""
    from apps.communications.assistant.tools import branch_hours
    from apps.organization.models import Branch
    branch = Branch.objects.filter(is_trading=True, is_active=True).order_by('pk').first()
    when = branch_hours(branch, now).get('next_opening') if branch else None
    if when:
        back = f" We're closed now and open again {'at' if ('today' in when or 'tomorrow' in when) else 'on'} {when}."
    else:
        back = " We're closed now."
    return (f"Got your file \U0001F44D{back} What would you like done with it? "
            "We'll get started as soon as we open.")


def _words_before(conversation, trigger, now, within=timedelta(minutes=10), anywhere=False):
    """
    The customer's last message before this file, in the last 10 minutes, said
    more than hello. With anywhere: any of their messages in that time did.
    """
    earlier = (conversation.messages
               .filter(direction=Message.INBOUND, pk__lt=trigger.pk, created_at__gte=now - within)
               .exclude(kind__in=Message.QUIET_KINDS).order_by('-pk'))
    if anywhere:
        return any(has_words(m.body or '') and not bare_greeting(m) for m in earlier[:20])
    before = earlier.first()
    return bool(before and has_words(before.body or '') and not bare_greeting(before))


NOT_SURE_REASON = 'greeted: not sure where they are'
NOT_SURE_GREETING = "Hi \U0001F44B How can I help you today?"
HOLD_REASON = 'held for the attendant'
HOLD_SECONDS = 120


BACK_AFTER = timedelta(hours=1)


def unsure_greeting(conversation, trigger, now):
    """
    The plain hello, or "Welcome back" for someone we served or spoke with
    earlier today: Hermann came back at 15:19 for a second job and got the
    same "How can I help you today?" as a stranger (23 Nov 2026). Their name
    when we know it, the way names.py allows.
    """
    from django.utils import timezone as tz
    from apps.communications.services import names
    start = tz.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    earlier = (conversation.messages
               .filter(is_internal_note=False, created_at__gte=start, created_at__lt=now - BACK_AFTER)
               .exclude(pk=trigger.pk))
    if not earlier.exists():
        return NOT_SURE_GREETING
    name = names.name_for(conversation)
    return f"Welcome back{', ' + name if name else ''} \U0001F60A How can I help you this time?"


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


def ack_text(conversation, branch, now=None):
    """
    The one acknowledgement at the counter (11 Nov 2026): warm, personal when
    Octos truly knows the name, never the customer's phone digits. A regular
    is welcomed back like one (20 Nov 2026), in words that change from one
    visit to the next.
    """
    name = (branch.name or '') if branch is not None else ''
    where = name[:-7] if name.endswith(' Branch') else name
    first = _first_name(conversation)
    shop = f'Farhat {where}' if where else 'Farhat'
    if is_regular(conversation, now):
        return _welcome_back(conversation, first, shop, now)
    hello = f'Hi {first} \U0001F44B' if first else 'Hi \U0001F44B'
    return (f"{hello} Welcome to {shop}. Hand your files to the attendant, "
            f"or drop them here and they'll pick them up.")


ACK_REASON = 'counter visit started'
FILES_LINES = (
    "Hand your files to the attendant, or drop them here and they'll pick them up.",
    "Drop your files here or hand them to the attendant, whichever is easier.",
    "Send your files here or give them to the attendant, and we'll take it from there.",
)


def is_regular(conversation, now=None):
    """They've had work done with us before today: Farhat knows them."""
    from apps.jobs.models import Job
    from django.db.models import Q
    where = Q(conversations=conversation)
    if conversation.customer_id:
        where |= Q(customer_id=conversation.customer_id)
    start = timezone.localtime(now or timezone.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    return (Job.objects.filter(where, created_at__lt=start)
            .exclude(status__in=[Job.CANCELLED, Job.VOIDED, Job.DRAFT]).exists())


def _day_part(now):
    hour = timezone.localtime(now or timezone.now()).hour
    return 'Good morning' if hour < 12 else ('Good afternoon' if hour < 17 else 'Good evening')


def _welcome_back(conversation, first, shop, now):
    """A different welcome each visit: the count of earlier ones picks it, so it never repeats back to back."""
    from apps.communications.models import AssistantRun
    you = f', {first}' if first else ''
    openings = (
        f'Welcome back{you} \U0001F60A',
        f'{_day_part(now)}{you}! Good to see you again.',
        f'Nice to have you back at {shop}{you} \U0001F44B',
        f'Hey{you}, good to see you again \U0001F60A',
    )
    seen = AssistantRun.objects.filter(conversation=conversation, reason=ACK_REASON).count()
    return f'{openings[seen % len(openings)]} {FILES_LINES[seen % len(FILES_LINES)]}'


def _first_name(conversation):
    """
    A registered customer's first name, from their customer record only.
    Never the WhatsApp profile name: "PEOPLE'S KOFI" is how "Hi People's"
    happened. A name we can't trust is worse than no name, and a name they
    corrected ("I'm not Mary") is never used again (names.py).
    """
    from apps.communications.services.names import name_for
    return name_for(conversation)


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
