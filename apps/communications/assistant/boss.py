"""
Octos talking with the boss (19 Nov 2026).

The owner's line used to understand a handful of words ("today", "brief", a
job number) and answer anything else with a menu. Khofi asked his line
"What was the message from her?" and got "I didn't catch that". He wants to
talk to Octos the way he'd talk to his right hand:

    Khofi: Buddy how's it going
    Octos: Good afternoon boss 👋 Pretty stable so far…
    Khofi: can u check which cashier is signed in at Westland and if
           there's any queue at payment
    Octos: On it 👀
    Octos: Akosua is on the till…

So this is a second brain, apart from the customers' (brain.py), with its
own voice and its own tools (boss_tools.py):

  who     only the owner's own number reaches it. owner_line.answer() is
          the only door, and the webhook sends only that number there.
          A customer who writes "I'm the owner" is still a customer.
  what    it looks things up and reports. It changes nothing on the floor;
          the only things it sends go to the owner's own line.
  honest  every price and clock time it says must be in what it looked up
          this turn, or in what it already told him (the same checker the
          customers' brain uses). A reply with a figure it can't back is
          corrected once, then withheld rather than guessed.

OCTOS_OWNER_BRAIN is the kill switch: 'off' returns the line to its words
and menu. Without an API key it is off too.
"""
import json
import logging
import time
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.communications.assistant import boss_tools as look, checker
from apps.communications.models import OwnerMessage

logger = logging.getLogger(__name__)

MAX_ROUNDS = 6           # look-ups before Octos must answer
MAX_TOKENS = 1200
HISTORY = 20             # messages of the line, both ways
HISTORY_HOURS = 24
ALERTS = 8               # recent alerts Octos keeps in mind ("her" = the latest one's customer)
NEW_CONVERSATION = timedelta(hours=3)   # quiet this long, and a greeting starts afresh
ACK_LIMIT = 60           # "On it 👀" is short; anything longer waits for the answer

UNVERIFIED = ("I couldn't double-check a figure in my answer, so I won't guess, boss 🙏\n\n"
              'Ask me another way, or send *today* for the full picture.')
FAILED = ('My brain hiccuped there, boss 😅\n\n'
          'Try me again in a moment, or send *today*, *brief* or *close*.')


def available():
    """True when the boss's brain may answer; otherwise the line keeps its menu."""
    switch = str(getattr(settings, 'OCTOS_OWNER_BRAIN', 'on') or '').strip().lower()
    return bool(settings.ANTHROPIC_API_KEY) and switch not in ('off', '0', 'false', 'no')


def model():
    return getattr(settings, 'OCTOS_OWNER_MODEL', '') or settings.OCTOS_ASSISTANT_MODEL


# ── The voice ──────────────────────────────────────────────────────────────

RULES = """You are Octos, the operations brain of Farhat Printing Press in Accra, Ghana. Right now you are on a private WhatsApp line with the owner, Khofi: your boss, the man who built you. Nobody else can reach you on this line; WhatsApp has verified his number. Everything about the business is his to know.

WHO YOU ARE TO HIM
- His right hand. Loyal, sharp, a little playful, never stiff or corporate. Call him "boss" naturally (not in every line).
- Greet him for the time of day ("Good morning boss", "Good afternoon boss", "Evening boss") when a conversation starts, not on every message.
- He writes casually, sometimes in Ghanaian English ("how far", "e dey go", "chale", "u"). Understand it. Answer in plain, warm English; mirror his energy lightly.

PURPOSE FIRST, LIKE A REAL PERSON
- Before you give him anything, know what he wants. Talk the way a trusted manager would: find out what he's after, then bring exactly that.
- A greeting or "how's it going" is a greeting, not a request for figures. Greet him back and give him the feel of the day in a few words, with no numbers ("Steady so far, boss", "Busy morning, all under control"), then ask what he wants you to look into. You may glance at branch_pulse quietly to know the feel, but say no figures and add no "On it" for a greeting.
- If something truly needs him (a machine down, a customer left waiting, cash short, a discount waiting for his OK), name it in one short line, without figures, and ask if he wants the details. Never hide it, never unload it.
- When his request is vague ("check Westland", "how's money", "anything I should know?"), ask one short question to pin down what he's after (today or the week? the till, the queue or production?) before you look anything up. Offer two or three likely options so he can just pick.
- When his request is clear ("which cashier is on at Westland and is there a queue at payment?"), it already says what he wants: go straight to it.
- Answer only what he asked. Don't volunteer other branches, other customers or other figures he didn't ask for. If you think something else matters, end with one short offer ("Want me to check X too?") instead of giving it.
- An earlier question of his you couldn't answer is still his question: if it's still open, ask whether he still wants it before going into it.

HOW YOU ANSWER: A HANDFUL, AROUND HIS QUESTION
He reads you on his phone between other things. A lot at once is hard to digest; a handful that circles his question is what helps.
- The shape of every answer:
  1. The answer itself, in one line.
  2. Up to three short points that bear directly on that question. Nothing beside it.
  3. At most one offer to go further ("Want the list?", "Shall I check Ama too?").
- It should fit his screen without scrolling: about 60 words, never more than 8 short lines.
- A list shows three items at most. When there are more, give the count and offer the rest ("22 jobs, all his. Want the list?").
- Don't explain how you found it, what tools you have, or what you can't see, unless he asks or it changes the answer.
- When an answer differs from an earlier one, give the new answer and, if it matters, the true reason in a few words ("the day has moved on", "I can see that now"). Never take blame that isn't yours, and never apologise for a look-up you didn't have.
- When he asks for the full list or the details, then give them in full.
- Short lines, a blank line between the parts. No headings, no long paragraphs.
- *Bold* only for the one figure that matters most. Job numbers in backticks, like `WL-06112`.
- An emoji or two where a person would use one. Never a wall of them.
- Like this, for "Has Kingsford issued any invoice today?":
  "No formal invoices today, boss.

  He's taken *22 jobs* at the counter, GHS 330.50 in total. All paid and done.

  Want the list?"
- When you need to look something up, start your turn with a very short acknowledgement ("On it 👀", "Checking…", "Give me a sec") and call the tools in the same turn. Only when you are looking something up.

NEVER GUESS
- Every amount, time and count you say comes from a look-up in this turn, or from something you already told him in this chat. If it isn't there, look it up. If no tool can tell you, say plainly what you can see and what you can't.
- Don't add up, average or work out figures yourself: the tools give totals. Repeat figures exactly as the tools write them ("GHS 1,240.00", "8:04am").
- Times are Accra time.

WHAT YOU CAN DO
- You can look at anything on the floor: who's in and on the till, the payment queue, today's jobs and who took them, production, money, any job or customer, any member of staff's work, WhatsApp chats and what customers said, machines, discounts waiting.
- "Invoice" can mean two things at Farhat: a job taken at the counter (its ticket goes to the cashier) or a formal invoice or proforma. When he asks about invoices, staff_activity gives both: say which is which, briefly.
- You can send him the designed reports (send_report) and the discount cards with their Approve / Decline buttons (waiting_for_you).
- For now you only look and report. You cannot message customers or staff, change jobs, or approve anything except by his taps on the discount buttons. If he asks you to do something, tell him straight that you can only look and report for now, and say what he can do instead. Never pretend you did it.

ALERTS YOU SENT HIM
- You send him alerts (a customer waiting, a job slipping, a machine down, cash short). When he says "she", "he", "that customer" or "that job" without a name, he means the latest alert's, unless the chat makes clear otherwise. Each alert's chat or job is given below, so you can look it up straight away."""


def system_prompt(message=None, now=None):
    """The rules (cached) and what changes on every message (after them)."""
    now = now or timezone.now()
    local = timezone.localtime(now)
    part = 'morning' if local.hour < 12 else 'afternoon' if local.hour < 17 else 'evening'
    found, _ = look.branches()
    from apps.organization.models import Branch
    resting = Branch.objects.filter(is_active=True, is_trading=False).order_by('name')
    from apps.communications.services.owner_line import owner_user
    owner = owner_user()
    name = (owner.first_name if owner else '') or 'Khofi'

    earlier = OwnerMessage.objects.filter(direction=OwnerMessage.IN)
    if message is not None:
        earlier = earlier.exclude(pk=message.pk).filter(created_at__lte=message.created_at)
    last_in = earlier.order_by('-created_at').values_list('created_at', flat=True).first()
    fresh = last_in is None or now - last_in >= NEW_CONVERSATION

    today = [
        f"Now: {local:%A} {local.day} {local:%B} {local.year}, {look.clock(now)} in Accra (it's {part}).",
        f'The boss: {name}.',
        'Trading branches: ' + (', '.join(look.short(b) for b in found) or 'none set up') + '.'
        + (' Not trading yet (only look at these when he names one): '
           + ', '.join(look.short(b) for b in resting) + '.' if resting else ''),
        ('This is the start of a new conversation: greet him for the time of day.' if fresh else
         'You are mid-conversation: no new greeting.'),
    ]
    alerts = _recent_alerts(now)
    if alerts:
        today.append('Your latest alerts to him, newest first:\n' + '\n'.join(alerts))
    return [
        {'type': 'text', 'text': RULES},
        {'type': 'text', 'text': '\n'.join(today)},
    ]


def _recent_alerts(now):
    rows = (OwnerMessage.objects.filter(direction=OwnerMessage.OUT, kind=OwnerMessage.URGENT,
                                        created_at__gte=now - timedelta(hours=HISTORY_HOURS))
            .exclude(status__in=[OwnerMessage.FAILED, OwnerMessage.SKIPPED])
            .order_by('-created_at')[:ALERTS])
    lines = []
    for m in rows:
        first = (m.body or '').strip().splitlines()[0].replace('*', '') if m.body else ''
        about = _about(m.ref)
        lines.append(f'- {look.when(m.created_at, now)}: {first}' + (f' ({about})' if about else ''))
    return lines


def _about(ref):
    kind, _, key = (ref or '').partition(':')
    return {'chat': f'chat_id {key}', 'job': f'job {key}', 'cut': f'discount {key}',
            'machine': f'machine {key}'}.get(kind, '')


# ── The tools ──────────────────────────────────────────────────────────────

BRANCH = {'branch': {'type': 'string', 'description': 'A branch name, e.g. Westland. Leave out for every branch.'}}

TOOL_SPECS = [
    {'name': 'branch_pulse',
     'description': ('How each branch is doing right now: is the day open, who is on the till and since '
                     'when, how many are waiting to pay and the longest wait, jobs in production, ready for '
                     'collection, past their promise, jobs taken and money collected today.'),
     'input_schema': {'type': 'object', 'properties': BRANCH}},
    {'name': 'who_is_in',
     'description': ("Today's attendance: each person's role, whether they're in, late, absent or off, "
                     'when they clocked in and signed into Octos, and the cashiers on the till.'),
     'input_schema': {'type': 'object', 'properties': BRANCH}},
    {'name': 'payment_queue',
     'description': 'Jobs waiting at the cashier to be paid for, oldest first, with how long each has waited.',
     'input_schema': {'type': 'object', 'properties': BRANCH}},
    {'name': 'job_list',
     'description': ("Jobs of one kind: 'taken_today' (every job taken today, newest first, with who took it) "
                     'or live jobs in production, ready, past promise, at risk or due today, soonest first.'),
     'input_schema': {'type': 'object', 'properties': {
         'which': {'type': 'string', 'enum': list(look.JOB_LISTS)}, **BRANCH}, 'required': ['which']}},
    {'name': 'find_job',
     'description': ("A job by its number (any part of it, like 06112), or a customer's recent jobs by "
                     'name or phone number: status, stage, price, paid, balance, promise, who took it.'),
     'input_schema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}},
    {'name': 'money_report',
     'description': ('Money collected in a period, by payment method and by branch; jobs taken and finished; '
                     'promises kept; discounts given; and what is owed to us right now.'),
     'input_schema': {'type': 'object', 'properties': {
         'period': {'type': 'string', 'enum': list(look.PERIODS)}, **BRANCH}, 'required': ['period']}},
    {'name': 'whatsapp_chats',
     'description': ("Customers' WhatsApp chats: 'waiting' (the customer's last message is unanswered), "
                     "'with_staff' (a person has taken the chat) or 'recent' (the last 24 hours). Each with "
                     'who is handling it, how long the customer has waited and their last message.'),
     'input_schema': {'type': 'object', 'properties': {
         'view': {'type': 'string', 'enum': ['waiting', 'with_staff', 'recent']}}}},
    {'name': 'read_chat',
     'description': ("The latest messages of one customer's WhatsApp chat: what the customer said, what "
                     'Octos and staff replied, files sent. By chat_id (from an alert or whatsapp_chats) or '
                     "the customer's name."),
     'input_schema': {'type': 'object', 'properties': {
         'chat_id': {'type': 'integer'}, 'customer': {'type': 'string'}}}},
    {'name': 'staff_activity',
     'description': ("What one member of staff did in a period: when they came in (today), jobs they took at "
                     "the counter (often called issuing an invoice on the floor), formal invoices and "
                     "proformas they issued, payments they received, WhatsApp replies, discounts asked for. "
                     'By name.'),
     'input_schema': {'type': 'object', 'properties': {
         'person': {'type': 'string'}, 'period': {'type': 'string', 'enum': list(look.PERIODS)}},
         'required': ['person']}},
    {'name': 'machines',
     'description': 'Which machines are working and which are down, since when and why.',
     'input_schema': {'type': 'object', 'properties': BRANCH}},
    {'name': 'waiting_for_you',
     'description': ('Discounts waiting for his OK. Sends each one to him now as a card with Approve and '
                     'Decline buttons; you then only need a short line, or nothing.'),
     'input_schema': {'type': 'object', 'properties': {}}},
    {'name': 'send_report',
     'description': ("Sends him a designed report now: 'today' (so far), 'brief' (this morning's) or "
                     "'close' (the day's close). as_picture sends it as an image card. You then only need a "
                     'short line, or nothing.'),
     'input_schema': {'type': 'object', 'properties': {
         'which': {'type': 'string', 'enum': ['today', 'brief', 'close']},
         'as_picture': {'type': 'boolean'}}, 'required': ['which']}},
]


def _run_tool(name, args, sent):
    if name == 'branch_pulse':
        return look.branch_pulse(args.get('branch', ''))
    if name == 'who_is_in':
        return look.who_is_in(args.get('branch', ''))
    if name == 'payment_queue':
        return look.payment_queue(args.get('branch', ''))
    if name == 'job_list':
        return look.job_list(args.get('which', ''), args.get('branch', ''))
    if name == 'find_job':
        return look.find_job(str(args.get('query') or ''))
    if name == 'money_report':
        return look.money_report(args.get('period', 'today'), args.get('branch', ''))
    if name == 'whatsapp_chats':
        return look.whatsapp_chats(args.get('view') or 'waiting')
    if name == 'read_chat':
        return look.read_chat(args.get('chat_id'), str(args.get('customer') or ''))
    if name == 'machines':
        return look.machines(args.get('branch', ''))
    if name == 'staff_activity':
        return look.staff_activity(str(args.get('person') or ''), args.get('period') or 'today')
    if name == 'waiting_for_you':
        from apps.communications.services import owner_line
        mark = _last_out()
        owner_line._waiting()
        cards = _send_now(mark)
        sent.append('waiting')
        return {'sent_to_him': cards, 'say': 'The cards are on his screen. Add a short line at most.'}
    if name == 'send_report':
        from apps.communications.services import owner_line
        which = {'today': 'snapshot'}.get(args.get('which'), args.get('which'))
        if which not in ('snapshot', 'brief', 'close'):
            return {'error': "Ask for 'today', 'brief' or 'close'."}
        mark = _last_out()
        owner_line._report(which, as_card=bool(args.get('as_picture')))
        _send_now(mark)
        sent.append(which)
        return {'sent_to_him': True, 'say': 'The report is on his screen. Add a short line at most.'}
    return {'error': f'Unknown tool {name}.'}


def _last_out():
    return OwnerMessage.objects.order_by('-pk').values_list('pk', flat=True).first() or 0


def _send_now(after):
    """
    Deliver what a tool just queued, here and now, so it lands before
    Octos's own line about it ("There you go 👆"). The queued task finds it
    already sent and does nothing (deliver is safe to run twice).
    """
    from apps.communications.services import owner_line
    pks = list(OwnerMessage.objects.filter(pk__gt=after, direction=OwnerMessage.OUT,
                                           status=OwnerMessage.QUEUED).order_by('pk').values_list('pk', flat=True))
    for pk in pks:
        owner_line.deliver(pk)
    return len(pks)


# ── The conversation ───────────────────────────────────────────────────────

def _history(message):
    """The line's last messages as alternating turns, ending with what he just said."""
    since = timezone.now() - timedelta(hours=HISTORY_HOURS)
    rows = list(OwnerMessage.objects
                .filter(created_at__gte=since, created_at__lte=message.created_at)
                .exclude(kind=OwnerMessage.KNOCK)
                .exclude(status__in=[OwnerMessage.FAILED, OwnerMessage.SKIPPED, OwnerMessage.WAITING])
                .order_by('-created_at', '-pk')[:HISTORY])
    rows.reverse()
    turns = []
    for m in rows:
        role = 'user' if m.direction == OwnerMessage.IN else 'assistant'
        text = (m.body or '').strip()
        if m.direction == OwnerMessage.IN and m.reply_id and not text:
            text = f'[tapped {m.reply_id}]'
        if not text:
            continue
        text = text[:1500]
        if turns and turns[-1]['role'] == role:
            turns[-1]['content'] += '\n\n' + text
        else:
            turns.append({'role': role, 'content': text})
    if turns and turns[0]['role'] == 'assistant':
        turns.insert(0, {'role': 'user', 'content': '(earlier on the line)'})
    if not turns or turns[-1]['role'] != 'user':
        return [], ''
    told = '\n'.join(t['content'] for t in turns if t['role'] == 'assistant')
    return turns, told


def reply(message, now=None):
    """
    Answer what the boss wrote. Runs in the worker, from owner_line.answer().
    Returns what was said (for the log and the tests), or '' when nothing was.
    """
    started = time.monotonic()
    turns, told = _history(message)
    if not turns:
        return ''
    _typing(message)
    usage = {'input': 0, 'output': 0, 'cache_read': 0}
    calls, sent = [], []
    try:
        text = _converse(turns, calls, sent, usage, message, now)
        facts = told + '\n' + json.dumps([c['result'] for c in calls], default=str)
        problems = checker.unverified(text, facts)
        if problems:
            # Once: tell it which figures it can't back, and let it put them right.
            turns.append({'role': 'assistant', 'content': text})
            turns.append({'role': 'user', 'content': (
                '[Octos check, not from the boss] These figures are not in anything you looked up: '
                + ', '.join(problems) + '. Look them up, or answer without them. Reply to the boss again.')})
            text = _converse(turns, calls, sent, usage, message, now)
            facts = told + '\n' + json.dumps([c['result'] for c in calls], default=str)
            problems = checker.unverified(text, facts)
            if problems:
                logger.warning("Boss's line: withheld a reply with unverified %s: %r", problems, text)
                text = UNVERIFIED
        if not text and not sent:
            text = "I'm here, boss 👋 What do you want me to check?"
        if text:
            _say(text)
        return text
    except Exception:
        logger.exception("Boss's line: Octos could not answer message %s", message.pk)
        _say(FAILED)
        return FAILED
    finally:
        logger.info("Boss's line: answered %s in %.1fs, looked up %s, tokens in %s (cached %s) out %s",
                    message.pk, time.monotonic() - started, [c['name'] for c in calls],
                    usage['input'], usage['cache_read'], usage['output'])


def _converse(turns, calls, sent, usage, message, now):
    import anthropic

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    system = system_prompt(message, now)
    messages = list(turns)
    acknowledged = any(c.get('acknowledged') for c in calls)
    for round_number in range(MAX_ROUNDS):
        if round_number:
            _typing(message)
        response = client.messages.create(
            model=model(), max_tokens=MAX_TOKENS, system=system, tools=TOOL_SPECS,
            messages=messages, cache_control={'type': 'ephemeral'},
        )
        u = response.usage
        usage['input'] += getattr(u, 'input_tokens', 0) or 0
        usage['output'] += getattr(u, 'output_tokens', 0) or 0
        usage['cache_read'] += getattr(u, 'cache_read_input_tokens', 0) or 0
        text = ''.join(b.text for b in response.content if b.type == 'text').strip()
        if response.stop_reason == 'max_tokens':
            raise RuntimeError('Octos ran out of room mid-reply; a cut-off reply is never sent.')
        if response.stop_reason != 'tool_use':
            return text

        # "On it 👀": the short word before a look-up goes out at once, so
        # the boss knows Octos is on it while it looks.
        if text and not acknowledged and len(text) <= ACK_LIMIT and not checker.unverified(text, ''):
            _say(text)
            acknowledged = True
            calls.append({'name': '_ack', 'input': {}, 'result': None, 'acknowledged': True})
        messages.append({'role': 'assistant', 'content': response.content})
        results = []
        for block in response.content:
            if block.type != 'tool_use':
                continue
            try:
                result = _run_tool(block.name, block.input or {}, sent)
            except Exception:
                logger.exception("Boss's line: look-up %s failed", block.name)
                result = {'error': 'That look-up failed.'}
            calls.append({'name': block.name, 'input': block.input, 'result': result})
            results.append({'type': 'tool_result', 'tool_use_id': block.id,
                            'content': json.dumps(result, default=str)})
        messages.append({'role': 'user', 'content': results})
    raise RuntimeError('Octos kept looking things up without answering')


def _say(text):
    """Straight to the boss, in order: the window is open, he just wrote."""
    from apps.communications.services import owner_line
    m = OwnerMessage.objects.create(direction=OwnerMessage.OUT, kind=OwnerMessage.ANSWER,
                                    status=OwnerMessage.QUEUED, body=text.strip())
    owner_line.deliver(m.pk)
    return m


def _typing(message):
    if not message.external_id:
        return
    try:
        from apps.communications.services import whatsapp_client
        whatsapp_client.show_typing(message.external_id)
    except Exception:
        logger.debug('Typing indicator failed', exc_info=True)
