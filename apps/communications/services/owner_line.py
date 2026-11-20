"""
The owner's private WhatsApp line (18 Nov 2026).

The owner is not always at a computer, so Octos reports to his own number:
the morning brief, the day's close, and anything urgent the moment it
happens, at any hour. He can answer: tap Approve or Decline on a discount,
send a shortcut ("today", "brief", "close", "waiting", a job number), or
just talk: anything else goes to Octos's brain for the boss (assistant/
boss.py, 19 Nov 2026), which looks things up and answers in plain words.

The number lives in the OCTOS_OWNER_PHONE setting (Railway), never in the
code: the repository is public. Messages from that number never reach the
inbox, the customer assistant or anyone's alerts; they are handled here and
kept in OwnerMessage.

WhatsApp only allows free messages for 24 hours after the owner last wrote.
When the window is shut, the message waits and one short approved template
(OWNER_TEMPLATE) knocks; his tap, or any message from him, opens the window
and everything waiting is sent, in order. Nothing waits silently.

Every hook into this file (discounts, machines, cash, chats, promises) goes
through _safely(): the owner's line must never break the work it reports on.
"""
import logging
import re
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.communications.models import OwnerMessage
from apps.communications.services.owner_reports import RULE, amount, table
from apps.core.phones import to_international

logger = logging.getLogger(__name__)

OWNER_TEMPLATE = 'owner_update'
OUTSIDE_WINDOW = '131047'
WINDOW = timedelta(hours=24)
MARGIN = timedelta(minutes=5)
KNOCK_GAP = timedelta(minutes=20)     # one knock at a time while he hasn't tapped
FOOTER = 'Octos · your business line'


# ── Who and when ───────────────────────────────────────────────────────────

def owner_phone():
    """The owner's number, international, or None when the line isn't set up."""
    return to_international(getattr(settings, 'OCTOS_OWNER_PHONE', '') or '') or None


def is_owner_number(phone):
    ours = owner_phone()
    return bool(ours and phone and to_international(phone) == ours)


def owner_user():
    from apps.accounts.models import CustomUser
    return CustomUser.objects.filter(is_business_owner=True, is_active=True).order_by('pk').first()


def window_open(now=None):
    last = (OwnerMessage.objects.filter(direction=OwnerMessage.IN)
            .order_by('-created_at').values_list('created_at', flat=True).first())
    return bool(last and (now or timezone.now()) < last + WINDOW - MARGIN)


def _safely(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception("Owner's line: %s failed", fn.__name__)
            return None
    return wrapper


# ── Sending ────────────────────────────────────────────────────────────────

def tell(kind, body, *, card=None, buttons=(), key=None, ref='', knock=''):
    """
    A message for the owner. Sent now if the window is open; otherwise kept
    WAITING and a template knocks. Returns the OwnerMessage, or None when
    there is no line or this key was already sent.
    """
    if not owner_phone():
        return None
    if key and OwnerMessage.objects.filter(key=key).exists():
        return None
    is_open = window_open()
    try:
        with transaction.atomic():
            message = OwnerMessage.objects.create(
                direction=OwnerMessage.OUT, kind=kind, body=body.strip(), buttons=list(buttons),
                card=card, key=key, ref=ref,
                status=OwnerMessage.QUEUED if is_open else OwnerMessage.WAITING,
            )
    except IntegrityError:
        return None          # the same event, told twice at once: once is enough
    if is_open:
        _queue(message.pk)
    else:
        _knock(knock or body.strip().splitlines()[0])
    return message


def _queue(pk):
    from apps.communications.tasks import deliver_owner_message
    transaction.on_commit(lambda: deliver_owner_message.delay(pk))


def _one_line(text, limit=600):
    """A template's {{1}}: one line, no tabs, no runs of spaces, not too long."""
    text = re.sub(r'\s+', ' ', str(text)).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _knock(line):
    """The template that tells the owner something is waiting. One at a time."""
    last_in = (OwnerMessage.objects.filter(direction=OwnerMessage.IN)
               .order_by('-created_at').values_list('created_at', flat=True).first())
    recent = OwnerMessage.objects.filter(kind=OwnerMessage.KNOCK,
                                         created_at__gte=timezone.now() - KNOCK_GAP)
    if last_in:
        recent = recent.filter(created_at__gt=last_in)
    if recent.exclude(status=OwnerMessage.FAILED).exists():
        return None
    waiting = OwnerMessage.objects.filter(status=OwnerMessage.WAITING).exclude(kind=OwnerMessage.KNOCK).count()
    words = _one_line(line)
    if waiting > 1:
        words = _one_line(f'{waiting} updates are waiting. Latest: {line}')
    knock = OwnerMessage.objects.create(direction=OwnerMessage.OUT, kind=OwnerMessage.KNOCK,
                                        status=OwnerMessage.QUEUED, body=words)
    _queue(knock.pk)
    return knock


def deliver(pk):
    """Send one QUEUED message to the owner. Runs in the worker; safe to run twice."""
    from apps.communications.services import whatsapp_client

    message = OwnerMessage.objects.filter(pk=pk, status=OwnerMessage.QUEUED).first()
    phone = owner_phone()
    if message is None or not phone:
        return
    card = bytes(message.card) if message.card else None
    try:
        if message.kind == OwnerMessage.KNOCK:
            wamid = whatsapp_client.send_template(phone, OWNER_TEMPLATE, params=[message.body])
        elif message.buttons:
            wamid = whatsapp_client.send_buttons(phone, message.body, message.buttons, image=card,
                                                 filename='octos.png', footer=FOOTER)
        elif card:
            wamid = whatsapp_client.send_image(phone, card, 'octos-report.png', caption=message.body[:1024])
        else:
            wamid = whatsapp_client.send_text(phone, message.body)
    except whatsapp_client.WhatsAppError as exc:
        if exc.code == OUTSIDE_WINDOW and message.kind != OwnerMessage.KNOCK:
            # Meta has the final word on the window: wait, and knock.
            OwnerMessage.objects.filter(pk=pk).update(status=OwnerMessage.WAITING)
            _knock(message.body.splitlines()[0] if message.body else 'An update is waiting')
        else:
            logger.warning("Owner's line: message %s failed: %s", pk, exc)
            OwnerMessage.objects.filter(pk=pk).update(status=OwnerMessage.FAILED, error=str(exc)[:500])
        return
    except Exception as exc:
        logger.exception("Owner's line: message %s could not be sent", pk)
        OwnerMessage.objects.filter(pk=pk).update(status=OwnerMessage.FAILED, error=f'internal: {exc!r}'[:500])
        return
    OwnerMessage.objects.filter(pk=pk, status=OwnerMessage.QUEUED).update(
        status=OwnerMessage.SENT, external_id=wamid, sent_at=timezone.now())


def _still_matters(message):
    """At sending time: is a waiting message still worth sending?"""
    if message.ref.startswith('cut:'):
        from apps.jobs.models import PriceCut
        return PriceCut.objects.filter(pk=message.ref.split(':')[1], status=PriceCut.Status.PENDING).exists()
    return True


def flush():
    """
    The window just opened: send everything waiting, oldest first. Only the
    newest brief and close go (an older one is out of date); a discount
    already decided is dropped. Returns how many were sent.
    """
    waiting = list(OwnerMessage.objects.filter(status=OwnerMessage.WAITING).order_by('created_at'))
    newest = {}
    for m in waiting:
        if m.kind in (OwnerMessage.BRIEF, OwnerMessage.CLOSE):
            newest[m.kind] = m.pk
    sent = 0
    for m in waiting:
        stale = m.kind in newest and newest[m.kind] != m.pk
        if stale or not _still_matters(m):
            OwnerMessage.objects.filter(pk=m.pk).update(status=OwnerMessage.SKIPPED)
            continue
        OwnerMessage.objects.filter(pk=m.pk, status=OwnerMessage.WAITING).update(status=OwnerMessage.QUEUED)
        deliver(m.pk)
        sent += 1
    return sent


# ── Receiving ──────────────────────────────────────────────────────────────

def receive(raw):
    """
    A message from the owner's number, straight from the webhook. Kept here,
    never in the inbox. True if new, False if Meta sent it twice.
    """
    body, reply_id = _words(raw)
    try:
        with transaction.atomic():
            message = OwnerMessage.objects.create(
                direction=OwnerMessage.IN, status=OwnerMessage.RECEIVED, body=body,
                reply_id=reply_id, external_id=raw.get('id') or None)
    except IntegrityError:
        return False
    from apps.communications.tasks import answer_owner
    transaction.on_commit(lambda: answer_owner.delay(message.pk))
    return True


def _words(raw):
    """(what he said, the button he tapped) from one WhatsApp message."""
    kind = raw.get('type') or ''
    if kind == 'text':
        return (raw.get('text') or {}).get('body', ''), ''
    if kind == 'interactive':
        chosen = (raw.get('interactive') or {})
        chosen = chosen.get('button_reply') or chosen.get('list_reply') or {}
        return chosen.get('title', ''), chosen.get('id', '')
    if kind == 'button':                 # a template's quick reply ("Open")
        button = raw.get('button') or {}
        return button.get('text', ''), button.get('payload', '') or 'open'
    if kind == 'reaction':
        return (raw.get('reaction') or {}).get('emoji', ''), ''
    media = raw.get(kind)
    return (media.get('caption', '') if isinstance(media, dict) else ''), ''


GREETINGS = {'hi', 'hello', 'hey', 'help', 'menu', 'morning', 'good morning', 'yo', 'start'}
TODAY = {'today', 'now', 'report', 'so far', 'how much', 'sales', 'money', 'how far'}
BRIEF = {'brief', 'morning brief', 'yesterday'}
CLOSE = {'close', 'day close', 'end of day', 'night', 'eod'}
WAITING_WORDS = {'waiting', 'approve', 'approvals', 'discount', 'discounts', 'pending'}
CARD_WORDS = {'card', 'picture', 'photo', 'image', 'pic'}

MENU = ('Octos here 🐙 Your business line.\n\n'
        'Send me:\n'
        '• *today* for the money and jobs so far\n'
        '• *brief* for this morning\'s brief\n'
        '• *close* for today\'s close so far\n'
        '• *waiting* for anything waiting for your OK\n'
        '• a *job number* (like 06009) to see where it is\n'
        '• add *card* for a picture: *card*, *brief card*, *close card*\n\n'
        'Urgent things come to you here the moment they happen.')


def answer(pk):
    """The owner wrote or tapped. Runs in the worker."""
    message = OwnerMessage.objects.filter(pk=pk, direction=OwnerMessage.IN).first()
    if message is None:
        return
    if message.reply_id.startswith('cut:'):
        _decide(message.reply_id)
    if message.reply_id.startswith('say:'):
        _say_tap(message.reply_id)
    sent = flush()
    if message.reply_id:
        # A tap is answered by what it opened; "Open" with nothing waiting
        # gets today so far rather than silence.
        if message.reply_id == 'open' and not sent:
            _report('snapshot')
        return
    words = re.sub(r'[^\w\s]', ' ', message.body.lower()).strip()
    words = re.sub(r'\s+', ' ', words)
    if not words:
        return
    said = set(words.split())
    # The shortcuts: one word (or a bare job number) gets its answer at once,
    # without the model. Anything else is a conversation (19 Nov 2026).
    if said & CARD_WORDS and len(said) <= 3:
        which = 'brief' if said & {'brief', 'morning', 'yesterday'} else 'close' if said & {'close', 'night', 'eod'} \
            else 'snapshot'
        return _report(which, as_card=True)
    if words in TODAY:
        return _report('snapshot')
    if words in BRIEF:
        return _report('brief')
    if words in CLOSE:
        return _report('close')
    if words in WAITING_WORDS:
        return _waiting()
    from apps.communications.assistant import boss
    talking = boss.available()
    job = re.fullmatch(r'(?:job\s*)?(?:[a-z]{2}\s*)?(\d{4,6})', words) if talking else \
        re.search(r'\b(\d{4,6})\b', words)
    if job:
        return _job(job.group(1))
    if sent and words in GREETINGS:
        return                                   # what was waiting is the answer
    if talking and words in ('menu', 'help'):
        return tell(OwnerMessage.ANSWER, MENU + '\n\nOr just ask me anything, in your own words 🙂')
    if talking:
        return boss.reply(message)
    if sent:
        return
    tell(OwnerMessage.ANSWER, MENU if words in GREETINGS else
         "I didn't catch that. " + MENU.split('\n\n', 1)[1])


def _report(which, key=None, as_card=False, **options):
    """
    A report as designed text (the default, 18 Nov 2026), or as the picture
    when the owner asks for a card. A picture that fails to draw goes as text.
    """
    from apps.communications.services import owner_cards, owner_reports
    report = getattr(owner_reports, which)(**options)
    kind = {'brief': OwnerMessage.BRIEF, 'close': OwnerMessage.CLOSE}.get(which, OwnerMessage.ANSWER)
    if as_card:
        try:
            card = owner_cards.render(report['card'])
            return tell(kind, report['caption'], card=card, knock=report['knock'], key=key)
        except Exception:
            logger.exception("Owner's line: the %s card could not be drawn", which)
    return tell(kind, report['text'], knock=report['knock'], key=key)


def _waiting():
    from apps.jobs.models import PriceCut
    cuts = list(PriceCut.objects.filter(status=PriceCut.Status.PENDING)
                .select_related('job', 'proforma', 'asked_by').order_by('created_at')[:5])
    if not cuts:
        return tell(OwnerMessage.ANSWER, 'Nothing is waiting for your OK right now. ✅')
    for cut in cuts:
        body, buttons = _cut_message(cut)
        tell(OwnerMessage.ANSWER, body, buttons=buttons)


def _job(digits):
    from apps.jobs.models import Job
    job = (Job.objects.filter(job_number__endswith=digits).select_related('customer', 'branch')
           .order_by('-created_at').first())
    if job is None:
        return tell(OwnerMessage.ANSWER, f"I couldn't find a job ending {digits}.")
    customer = job.customer.full_name if job.customer_id else ''
    rows = [('Status', job.get_status_display()),
            ('Price', amount(job.estimated_cost)), ('Paid', amount(job.amount_paid))]
    if job.estimated_ready_at:
        rows.append(('Promised', timezone.localtime(job.estimated_ready_at).strftime('%a %d %b %H:%M')))
    if job.promise_state in ('AT_RISK', 'LATE', 'BROKEN'):
        rows.append(('Promise', job.promise_state.replace('_', ' ').lower()))
    lines = [f'🔎 `{job.job_number}`', job.title + (f' · {customer}' if customer else ''), table(rows)]
    if job.discount_amount:
        lines.append(f'> 🏷️ {amount(job.discount_amount)} off · {job.discount_reason}')
    return tell(OwnerMessage.ANSWER, '\n'.join(lines))


def _decide(reply_id):
    from apps.jobs.models import PriceCut
    from apps.jobs.services import discounts
    _, action, cut_id = (reply_id.split(':') + ['', ''])[:3]
    owner = owner_user()
    cut = PriceCut.objects.select_related('job', 'proforma', 'asked_by').filter(pk=cut_id or 0).first()
    if cut is None or owner is None:
        return tell(OwnerMessage.ANSWER, "I couldn't find that discount any more.")
    label = cut.job.job_number if cut.job_id else cut.proforma.proforma_number
    asker = cut.asked_by.first_name if cut.asked_by_id else 'The manager'
    try:
        if action == 'approve':
            discounts.approve(owner, cut.pk)
            return tell(OwnerMessage.ANSWER, f'✅ Approved. {label} is now GHS {cut.new_total:,.2f}. '
                                             f'{asker} has been told.')
        discounts.decline(owner, cut.pk, 'Declined on WhatsApp')
        return tell(OwnerMessage.ANSWER, f'❌ Declined. {label} stays at GHS {cut.before_total:,.2f}. '
                                         f'{asker} has been told.')
    except discounts.DiscountRefused as refused:
        return tell(OwnerMessage.ANSWER, f'{label}: {refused}')


def _say_tap(reply_id):
    """Send or Cancel on words Octos drafted for a customer (19 Nov 2026)."""
    from apps.communications.models import Conversation
    from apps.communications.services import owner_watch
    _, action, conversation_id = (reply_id.split(':') + ['', ''])[:3]
    draft = (OwnerMessage.objects.filter(direction=OwnerMessage.OUT, ref=f'say:{conversation_id}')
             .exclude(draft='').order_by('-created_at').first())
    if draft is None:
        return tell(OwnerMessage.ANSWER, 'That draft has already been dealt with.')
    words = draft.draft
    OwnerMessage.objects.filter(pk=draft.pk).update(draft='')
    if action != 'send':
        return tell(OwnerMessage.ANSWER, 'Cancelled. Nothing was sent.')
    conversation = Conversation.objects.filter(pk=conversation_id).first()
    if conversation is None:
        return tell(OwnerMessage.ANSWER, "I couldn't find that chat any more.")
    result = owner_watch.send_for_owner(conversation, words)
    return tell(OwnerMessage.ANSWER, result.get('say') or f'Sent to {conversation.display_name} ✅')


# ── What Octos tells the owner ─────────────────────────────────────────────

def _cut_message(cut):
    target = cut.job or cut.proforma
    label = cut.job.job_number if cut.job_id else cut.proforma.proforma_number
    customer = target.customer.full_name if getattr(target, 'customer_id', None) else ''
    pct = (cut.before_total - cut.new_total) / cut.before_total * 100 if cut.before_total else 0
    rows = [('Price', amount(cut.before_total)), ('Asked', amount(cut.new_total)), ('Off', f'{pct:.1f}%')]
    if cut.cost is not None and cut.floor_total is not None:
        rows += [('Cost', amount(cut.cost)), ('BM floor', amount(cut.floor_total))]
    else:
        rows.append(('Cost', 'not all set'))
    who = cut.asked_by.full_name if cut.asked_by_id else 'The manager'
    lines = ['⚠️ *A discount is waiting for you*', RULE, f'`{label}`']
    if customer:
        lines.append(customer)
    lines += [table(rows), RULE, f'{who}: _"{cut.reason}"_']
    buttons = [{'id': f'cut:approve:{cut.pk}', 'title': 'Approve'},
               {'id': f'cut:decline:{cut.pk}', 'title': 'Decline'}]
    return '\n'.join(lines), buttons


@_safely
def price_cut_waiting(cut):
    body, buttons = _cut_message(cut)
    label = cut.job.job_number if cut.job_id else cut.proforma.proforma_number
    return tell(OwnerMessage.URGENT, body, buttons=buttons, key=f'cut:{cut.pk}', ref=f'cut:{cut.pk}',
                knock=f'A discount on {label} is waiting for your OK: GHS {cut.new_total:,.2f}.')


@_safely
def machine_down(machine):
    since = timezone.localtime(machine.unavailable_since or timezone.now())
    branch = machine.branch.name if machine.branch_id else ''
    body = (f'🛑 *{machine.name} is down*\n_{branch} · since {since:%H:%M}_\n'
            f'> {machine.unavailable_reason or "No reason given"}')
    return tell(OwnerMessage.URGENT, body, key=f'machine-down:{machine.pk}:{since:%Y%m%d%H%M}',
                knock=f'{machine.name} at {branch} is down since {since:%H:%M}.')


@_safely
def cash_short(float_record):
    short = -(float_record.variance or 0)
    if short <= 0:
        return None
    who = float_record.cashier.full_name if float_record.cashier_id else 'The cashier'
    note = (float_record.variance_notes or '').strip()
    body = '\n'.join(filter(None, [
        f'💸 *Cash short GHS {short:,.2f}* at sign-off', RULE,
        table([('Cashier', who), ('Expected', amount(float_record.expected_cash)),
               ('Counted', amount(float_record.closing_cash)), ('Short', amount(short))]),
        note and f'> Their note: _"{note}"_']))
    return tell(OwnerMessage.URGENT, body, key=f'cash-short:{float_record.pk}',
                knock=f'Cash was short GHS {short:,.2f} at {who}\'s sign-off.')


@_safely
def customer_waiting(conversation, minutes):
    """
    A customer left waiting by the person who took their chat. Shows what
    they actually wrote (19 Nov 2026: the owner had to ask "what was the
    message from her?"), and who took the chat.
    """
    name = conversation.display_name
    who = conversation.assigned_to.first_name if conversation.assigned_to_id else 'A person'
    lines = [f'⏳ *{name} has waited {minutes} minutes*',
             f'_{who} took the chat and hasn\'t replied._']
    said = _unanswered(conversation)
    if said:
        lines += ['', f'_{name} said:_'] + [f'> {line}' for line in said]
    lines += ['', "_I'll take it back in 10 minutes if nobody answers._"]
    return tell(OwnerMessage.URGENT, '\n'.join(lines),
                key=f'waiting:{conversation.pk}:{timezone.now():%Y%m%d%H}', ref=f'chat:{conversation.pk}',
                knock=f'{name} has waited {minutes} minutes for a reply on WhatsApp.')


def _unanswered(conversation, limit=3):
    """The customer's messages since Farhat last spoke, newest last: words, or what the file was."""
    from apps.communications.models import Message
    recent = list(conversation.messages.filter(is_internal_note=False)
                  .exclude(kind__in=Message.QUIET_KINDS).order_by('-created_at')[:12])
    theirs, files = [], 0
    for m in recent:
        if m.direction != Message.INBOUND:
            break
        if m.message_type in (Message.IMAGE, Message.VIDEO, Message.DOCUMENT, Message.AUDIO):
            files += 1
            if m.body:
                theirs.append(_clip(m.body))
        elif m.body:
            theirs.append(_clip(m.body))
    theirs = theirs[:limit][::-1]
    if files:
        theirs.append(f'📎 {files} file{"s" if files > 1 else ""}')
    return theirs


def _clip(text, limit=160):
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


@_safely
def job_slipping(job, word, when):
    customer = job.customer.full_name if job.customer_id else ''
    heading = '🔴 *Past its promise*' if word == 'late' else '🟠 *At risk of running late*'
    body = (f'{heading}\n`{job.job_number}` · {job.title}' + (f' · {customer}' if customer else '')
            + f'\n> Now about {when}')
    return tell(OwnerMessage.URGENT, body, key=f'promise:{job.pk}:{word}:{timezone.localdate():%Y%m%d}',
                knock=f'{job.job_number} is {word}: now about {when}.')


@_safely
def send_brief():
    """The 7:30 brief, opening with the time and the weather (20 Nov 2026)."""
    from apps.communications.services import weather
    try:
        greeting = weather.morning_greeting()
    except Exception:
        logger.exception("Owner's line: the morning greeting failed; the brief goes without it")
        greeting = None
    return _report('brief', key=f'brief:{timezone.localdate():%Y-%m-%d}', greeting=greeting)


@_safely
def send_close():
    return _report('close', key=f'close:{timezone.localdate():%Y-%m-%d}')
