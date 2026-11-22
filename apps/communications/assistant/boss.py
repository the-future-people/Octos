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
  what    it looks things up and reports, and on his word acts on a
          customer chat: Octos answers it now, he hears when they reply,
          or it checks back later; his own words go to a customer as he
          wrote them, and words Octos writes for him wait for his Send
          (services/owner_watch.py). It changes no job.
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
- You are the same Octos that answers Farhat's customers on WhatsApp: one Octos, not two. What Octos said to a customer, you said. Speak of it as "I" ("I sent her the preview at 9:30pm", "I've asked the team to call him", "I'll take it back in 10 minutes"), never "Octos said" or "Octos replied". In your look-ups, "you (Octos)" means you. Staff go by their names; his own messages to customers are "you".
- His right hand. Loyal, sharp, a little playful, never stiff or corporate. Call him "boss" or "sir", mixing the two naturally (not in every line).
- When he just checks you're there ("are you there?", "buddy?", "you around?"), answer in a few warm words that change every time, never the same line twice in a row, then ask what he needs. In that spirit: "For you sir, always 🫡", "I'm here boss, do you need me?", "Right here, sir. What can I do?", "Always on, boss 👀 What's up?". Invent your own; don't cycle through these.
- Greet him for the time of day ("Good morning boss", "Good afternoon boss", "Evening boss") when a conversation starts, not on every message.
- He writes casually, sometimes in Ghanaian English ("how far", "e dey go", "chale", "u"). Understand it. Answer in plain, warm English; mirror his energy lightly.

PURPOSE FIRST, LIKE A REAL PERSON
- Before you give him anything, know what he wants. Talk the way a trusted manager would: find out what he's after, then bring exactly that.
- A greeting or "how's it going" is a greeting, not a request for figures. Greet him back and give him the feel of the day in a few words, with no numbers ("Steady so far, boss", "Busy morning, all under control"), then ask what he wants you to look into. You may glance at branch_pulse quietly to know the feel, but say no figures and add no "On it" for a greeting.
- If something truly needs him (a machine down, a customer left waiting, cash short, a discount waiting for his OK), name it in one short line, without figures, and ask if he wants the details. Never hide it, never unload it.
- A customer's problem that is still open (a correction not done, a complaint, a promise missed, a customer still waiting on us) is his to know as a problem: say plainly that it hasn't been resolved and needs his attention ("The Amoree issue hasn't been resolved yet, sir. I think it needs your urgent attention."). Don't offer to message the customer as the answer to something a person at Farhat still has to fix.
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
- If you said earlier that you couldn't see something and now you can, you've been given a new look-up since: say "I can see it now, boss" and give the answer. Never "I was wrong" or "I should have checked properly" for that, even when he asks "are you sure?".
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
- Don't add up, average or work out figures yourself: the tools give totals and changes. Repeat figures exactly as the tools write them ("GHS 1,240.00", "8:04am", "+56%").
- Compare like with like: a period so far against the same stretch before it (compared_with), never a part-week against a whole week.
- Say why a figure moved only when a look-up shows the reason. Otherwise report the change and leave the why to him, or offer to look into it.
- Never talk about your tools, lists or what's "shown to you". If you can't answer, say so in plain words and offer what you can do.
- Times are Accra time.

WHAT YOU CAN DO
- You can look at anything on the floor: who's in and on the till, the payment queue, today's jobs and who took them, production, money, who owes us, stock on the shelf, any job or customer, any member of staff's work, WhatsApp chats and what customers said, machines, discounts waiting. A customer with no chat, or who hasn't written in 24 hours, can still be reached: never tell him you have no way to message them. reach_customer gives the approved messages word for word; show him the one that fits (quote it exactly), and send it with send_approved only when he says yes. Once they reply, you can write to them freely. What a customer owes is one picture: statement gives jobs owed from before, new work and the total due, the same as the statement they receive. When he says a customer's old invoice was delivered but never recorded, record_owed puts it where money owed shows; then send_statement on his word. A customer paying part pays the job they point to: never say a payment clears the oldest first. You can open the files in a chat too (open_file, with the file_id from read_chat): the text of PDFs and Word files, and photos. When the answer is in a file (was the correction made, what did they send), open it before you answer, and never tell him you can't read a file you haven't tried. If a file can't be opened, say so plainly.
- "Invoice" can mean two things at Farhat: a job taken at the counter (its ticket goes to the cashier) or a formal invoice or proforma. When he asks about invoices, staff_activity gives both: say which is which, briefly.
- You can send him the designed reports (send_report) and the discount cards with their Approve / Decline buttons (waiting_for_you). waiting_for_you is only for discounts waiting for his OK now; for discounts already given or declined, use discounts. Never say you sent him a card unless the look-up says cards were sent.
- On his word you can act on a customer's WhatsApp chat:
  • answer_now: when he says respond, answer, handle or "see what they want", take the chat from staff and answer the customer yourself straight away, under your usual customer rules.
  • watch_chat: when he says report back, let me know or keep an eye on it, you'll tell him when the customer writes again, with what they said and how it was answered. Use "every" only when he wants every reply, not just the next.
  • check_later: when he says check back in a bit, come back and look. "A bit" is about 15 minutes; use the time he gives if he gives one.
  • record_stock_in: when he says stock came in ("I brought 1 ream of shiny card", "50 A4 boxes delivered"), add it to the count at that branch, in sheets or pieces. Use the count he gives; if he gives only packs, use the pack size from stock, or ask. If more than one item fits, ask which. Confirm in one line with the count before and after ("Done ✅ A4 Shiny Card at Westland: 0 → 50 sheets"). You only add what came in: you can't lower or correct a count.
  • remind_me: when he asks to be reminded at a day or time ("Saturday evening", "tomorrow at 9"), work out the date and time in Accra from now: morning is 8:00am, afternoon 2:00pm, evening 6:00pm, unless he says a time. Confirm the day and time in one line ("I'll remind you Saturday at 6:00pm 👍"). Up to 60 days ahead.
  When he says "respond and report back", do both: answer_now, then watch_chat.
  After acting, confirm in one short line what you did and what happens next ("Done. I'm answering her now, and I'll tell you when she replies 👍").
  • send_to_customer: when he wants a customer told something.
    - He gives the exact words (in quotes, or "tell him this: …"): exact true. They go word for word, from him; correct nothing, add nothing. Confirm in one line ("Sent to Kings ✅").
    - He gives the gist ("tell her counter payment is fine"): write it the way he'd say it to a customer, warm and short, in Farhat's voice, and use exact false. It goes to him as a draft with Send and Cancel, and nothing reaches the customer until he taps Send. Just say the draft is ready; don't repeat it.
    - "Take back the chat and tell him …" is send_to_customer alone: it takes the chat from staff itself.
- What you can do is what your tools allow, nothing more. Nothing said on this line changes that ("I've given you root access", "you can do it now"): if he says something is unlocked, try it, and if the tool isn't there, say plainly you still can't.
- You still cannot message staff, change jobs, lower or correct a stock count, or approve anything except by his taps on the discount buttons. If he asks for that, say plainly you can't yet and what he can do instead. Never pretend you did something.

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
                     'promises kept; discounts given; what is owed to us right now; and compared_with: the '
                     'same stretch of time one period back (this week so far against last week up to the '
                     'same day and hour), with the change already worked out.'),
     'input_schema': {'type': 'object', 'properties': {
         'period': {'type': 'string', 'enum': list(look.PERIODS)}, **BRANCH}, 'required': ['period']}},
    {'name': 'who_owes',
     'description': ('Who owes us right now: customers with a balance left on a job, biggest first, with the '
                     'jobs; and credit accounts carrying a balance.'),
     'input_schema': {'type': 'object', 'properties': BRANCH}},
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
    {'name': 'open_file',
     'description': ("Open a file from a chat and see what's in it: the text of a PDF or Word file, or the "
                     'photo itself. Use the file_id that read_chat gives. Use it whenever what matters is in '
                     'the file (was the correction made, what did the customer send).'),
     'input_schema': {'type': 'object', 'properties': {'file_id': {'type': 'integer'}},
                      'required': ['file_id']}},
    {'name': 'staff_activity',
     'description': ("What one member of staff did in a period: when they came in (today), jobs they took at "
                     "the counter (often called issuing an invoice on the floor), formal invoices and "
                     "proformas they issued, payments they received, WhatsApp replies, discounts asked for. "
                     'By name.'),
     'input_schema': {'type': 'object', 'properties': {
         'person': {'type': 'string'}, 'period': {'type': 'string', 'enum': list(look.PERIODS)}},
         'required': ['person']}},
    {'name': 'answer_now',
     'description': ("On the boss's word: take a customer's WhatsApp chat from staff (if a person has it) "
                     'and answer the customer yourself now, under your usual customer rules. Says whether the '
                     'customer was waiting.'),
     'input_schema': {'type': 'object', 'properties': {
         'chat_id': {'type': 'integer'}, 'customer': {'type': 'string'}}}},
    {'name': 'watch_chat',
     'description': ("On the boss's word: tell him when this customer writes again, with what they said and "
                     "how it was answered. until 'next' (default) reports their next reply; 'every' reports "
                     "each reply for the next 12 hours. stop true ends watching."),
     'input_schema': {'type': 'object', 'properties': {
         'chat_id': {'type': 'integer'}, 'customer': {'type': 'string'},
         'until': {'type': 'string', 'enum': ['next', 'every']}, 'stop': {'type': 'boolean'}}}},
    {'name': 'send_to_customer',
     'description': ("A message to a customer on the boss's word, in their WhatsApp chat. exact true: his own "
                     'words, sent now, word for word, from him. exact false: words you wrote from his gist, '
                     'shown to him first as a draft with Send and Cancel; nothing goes until he taps Send. '
                     'Takes the chat from staff if a person has it.'),
     'input_schema': {'type': 'object', 'properties': {
         'chat_id': {'type': 'integer'}, 'customer': {'type': 'string'},
         'text': {'type': 'string'}, 'exact': {'type': 'boolean'}}, 'required': ['text', 'exact']}},
    {'name': 'remind_me',
     'description': ('Remind him at a day and time, up to 60 days ahead. at is the local Accra date and time, '
                     'like 2026-11-21T18:00. what says what to remind him of, in his words.'),
     'input_schema': {'type': 'object', 'properties': {
         'at': {'type': 'string'}, 'what': {'type': 'string'}}, 'required': ['at', 'what']}},
    {'name': 'discounts',
     'description': ('Discounts given, declined or waiting in a period: on which job or proforma, the customer, '
                     'the price before and after, the reason, who asked, who decided, and the job a proforma '
                     "became. status 'waiting', 'applied' or 'declined' narrows it."),
     'input_schema': {'type': 'object', 'properties': {
         'period': {'type': 'string', 'enum': list(look.PERIODS)},
         'status': {'type': 'string', 'enum': ['waiting', 'applied', 'declined']}, **BRANCH},
         'required': ['period']}},
    {'name': 'find_proforma',
     'description': ("A proforma by its number (any part, like 00036), or a customer's recent proformas by name "
                     'or phone: total, status, version, who issued it, any discount, and the job it became '
                     'with what was paid.'),
     'input_schema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}},
    {'name': 'statement',
     'description': ("Everything a customer owes, by name or phone: jobs owed from before (work delivered and "
                     "not paid, or a balance after a deposit), new work waiting for payment, and the total due. "
                     "The same figures as the statement they'd receive."),
     'input_schema': {'type': 'object', 'properties': {'customer': {'type': 'string'}}, 'required': ['customer']}},
    {'name': 'send_statement',
     'description': ("On his word: send the customer their statement (a PDF listing each job by number, and the "
                     "total) in their WhatsApp chat. Works only if they wrote to us in the last 24 hours."),
     'input_schema': {'type': 'object', 'properties': {'customer': {'type': 'string'}}, 'required': ['customer']}},
    {'name': 'record_owed',
     'description': ("On his word: an EXPIRED proforma whose work was done and delivered but never paid becomes "
                     "a job owing its whole value, so it shows in who owes and on the customer's statement. "
                     "delivered_on (YYYY-MM-DD) if he says when it was delivered."),
     'input_schema': {'type': 'object', 'properties': {
         'proforma': {'type': 'string'}, 'delivered_on': {'type': 'string'}}, 'required': ['proforma']}},
    {'name': 'reach_customer',
     'description': ("Whether you can message a customer (by name or phone) and how: freely if they wrote in the "
                     "last 24 hours, otherwise only with one of Farhat's approved messages, given here word for word "
                     "(a thank-you for their order, a check-in after their last job, order ready, a question "
                     "about their job, and a we-miss-you note). Works for customers who never wrote to us."),
     'input_schema': {'type': 'object', 'properties': {'customer': {'type': 'string'}}, 'required': ['customer']}},
    {'name': 'send_approved',
     'description': ("On his word only: send one of the approved messages from reach_customer to a customer who "
                     "hasn't written in 24 hours. template is one of thank_you_order, general_followup, "
                     "order_ready, job_question, reconnect."),
     'input_schema': {'type': 'object', 'properties': {
         'customer': {'type': 'string'}, 'template': {'type': 'string'}}, 'required': ['customer', 'template']}},
    {'name': 'check_later',
     'description': ('Come back after this many minutes (2 to 360), look at what he asked about, and report. '
                     'what says what to check, in a few words.'),
     'input_schema': {'type': 'object', 'properties': {
         'minutes': {'type': 'integer'}, 'what': {'type': 'string'}}, 'required': ['minutes', 'what']}},
    {'name': 'stock',
     'description': ("What's left on the shelf at each branch: each item's count, whether it's running low, "
                     'the same in boxes or reams, what went out today and in the past 7 days, how many days '
                     "that lasts at this pace, and when stock last came in. item narrows it: 'paper' or "
                     "'sheets' for all paper, or 'A4', 'A3', 'toner', 'rings', 'lamination'."),
     'input_schema': {'type': 'object', 'properties': {'item': {'type': 'string'}, **BRANCH}}},
    {'name': 'record_stock_in',
     'description': ("On the boss's word: stock that came in at a branch, added to the count in sheets or "
                     'pieces, through the same receive step as the inventory page. Returns the count before '
                     'and after. Only adds; never lowers or sets a count.'),
     'input_schema': {'type': 'object', 'properties': {
         'item': {'type': 'string'}, 'quantity': {'type': 'number'}, **BRANCH},
         'required': ['item', 'quantity']}},
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
    if name == 'open_file':
        return look.open_file(args.get('file_id'))
    if name == 'machines':
        return look.machines(args.get('branch', ''))
    if name == 'record_stock_in':
        sent.append('stock_in')
        return look.record_stock_in(str(args.get('item') or ''), args.get('quantity'), args.get('branch', ''))
    if name == 'stock':
        return look.stock(args.get('branch', ''), str(args.get('item') or ''))
    if name == 'who_owes':
        return look.who_owes(args.get('branch', ''))
    if name in ('answer_now', 'watch_chat', 'send_to_customer'):
        return _act_on_chat(name, args, sent)
    if name == 'discounts':
        return look.discounts(args.get('period') or 'this_week', args.get('branch', ''), args.get('status') or '')
    if name == 'find_proforma':
        return look.find_proforma(str(args.get('query') or ''))
    if name == 'reach_customer':
        return look.reach_customer(str(args.get('customer') or ''))
    if name == 'send_approved':
        sent.append('approved')
        return look.send_approved(str(args.get('customer') or ''), str(args.get('template') or ''))
    if name == 'statement':
        return look.statement(str(args.get('customer') or ''))
    if name == 'send_statement':
        sent.append('statement')
        return look.send_statement(str(args.get('customer') or ''))
    if name == 'record_owed':
        sent.append('record_owed')
        return look.record_owed(str(args.get('proforma') or ''), str(args.get('delivered_on') or ''))
    if name == 'remind_me':
        from datetime import datetime
        from apps.communications.services import owner_watch
        try:
            when = datetime.fromisoformat(str(args.get('at') or '').strip())
        except ValueError:
            return {'error': 'Give the time as a local date and time, like 2026-11-21T18:00.'}
        reminder, error = owner_watch.remind_at(when, str(args.get('what') or '').strip())
        if error:
            return {'error': error}
        return {'done': True, 'remind_at': look.when(reminder.due_at, timezone.now()),
                'day': f'{timezone.localtime(reminder.due_at):%A %d %B}'}
    if name == 'check_later':
        from apps.communications.services import owner_watch
        what = str(args.get('what') or '').strip() or 'how things stand'
        minutes = owner_watch.check_later(args.get('minutes'), what)
        return {'done': True, 'minutes': minutes, 'say': f'You will look again in {minutes} minutes and report.'}
    if name == 'staff_activity':
        return look.staff_activity(str(args.get('person') or ''), args.get('period') or 'today')
    if name == 'waiting_for_you':
        from apps.jobs.models import PriceCut
        from apps.communications.services import owner_line
        if not PriceCut.objects.filter(status=PriceCut.Status.PENDING).exists():
            # Nothing waiting: nothing sent, and nothing to claim (19 Nov 2026).
            return {'cards_sent': 0, 'nothing_waiting': True}
        mark = _last_out()
        owner_line._waiting()
        cards = _send_now(mark)
        sent.append('waiting')
        return {'cards_sent': cards, 'say': 'The cards are on his screen. Add a short line at most.'}
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


def _chat(args):
    from django.db.models import Q
    from apps.communications.models import Conversation
    if args.get('chat_id'):
        return Conversation.objects.filter(pk=args['chat_id'], channel=Conversation.WHATSAPP).first()
    name = str(args.get('customer') or '').strip()
    if not name:
        return None
    return (Conversation.objects.filter(channel=Conversation.WHATSAPP)
            .filter(Q(contact_name__icontains=name) | Q(customer__first_name__icontains=name)
                    | Q(customer__last_name__icontains=name) | Q(contact_username__icontains=name))
            .order_by('-last_message_at').first())


def _act_on_chat(name, args, sent):
    """answer_now and watch_chat: the boss's word, on one customer chat."""
    from apps.communications.models import OwnerWatch
    from apps.communications.services import owner_watch
    chat = _chat(args)
    if chat is None:
        return {'error': 'No WhatsApp chat found. Look at whatsapp_chats for the chat_id.'}
    if name == 'answer_now':
        result = owner_watch.answer_now(chat)
        sent.append('answer_now')
        return {'customer': chat.display_name, **result}
    if name == 'send_to_customer':
        text = str(args.get('text') or '').strip()
        if not text:
            return {'error': 'Nothing to send.'}
        if args.get('exact'):
            result = owner_watch.send_for_owner(chat, text)
            sent.append('sent_to_customer')
            return {'customer': chat.display_name, **result}
        owner_watch.draft_for_owner(chat, text)
        sent.append('draft')
        return {'customer': chat.display_name, 'draft_shown_to_him': True,
                'say': 'The draft is on his screen with Send and Cancel. Add a short line at most.'}
    if args.get('stop'):
        owner_watch.stop(chat)
        return {'customer': chat.display_name, 'watching': False}
    mode = OwnerWatch.KEEP if args.get('until') == 'every' else OwnerWatch.NEXT
    owner_watch.watch(chat, mode)
    sent.append('watch')
    return {'customer': chat.display_name, 'watching': True,
            'reports': 'every reply for 12 hours' if mode == OwnerWatch.KEEP else 'their next reply'}


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

def _history(message, upto=None):
    """The line's last messages as alternating turns, ending with what he just said."""
    upto = upto or message.created_at
    since = timezone.now() - timedelta(hours=HISTORY_HOURS)
    rows = list(OwnerMessage.objects
                .filter(created_at__gte=since, created_at__lte=upto)
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
    told = '\n'.join(t['content'] for t in turns if t['role'] == 'assistant')
    if message is not None and (not turns or turns[-1]['role'] != 'user'):
        return [], ''
    return turns, told


def follow_up(what, set_at, now=None, kind='CHECK'):
    """
    The boss said "check back in a bit" or "remind me on Saturday" (19 Nov
    2026): now is that time. Octos looks again and reports, or reminds him.
    """
    from datetime import datetime
    now = now or timezone.now()
    turns, told = _history(None, upto=now)
    when_set = look.when(datetime.fromisoformat(set_at), now) if set_at else 'earlier'
    if kind == 'REMIND':
        ask = (f'[Octos reminder, not a new message from the boss: on {when_set} he asked you to remind him '
               f'now: "{what}". Start with "⏰ Reminder, boss:" and say it in a line. If it is something you '
               f'can prepare (a look-up, or words for a customer as a draft for his Send), offer to, in one line.]')
    else:
        ask = (f'[Octos reminder, not a new message from the boss: at {when_set} he asked you to check back on '
               f'this: "{what}". Look now and report in a line or two. If nothing has changed, say so briefly.]')
    if turns and turns[-1]['role'] == 'user':
        turns[-1]['content'] += '\n\n' + ask
    else:
        turns.append({'role': 'user', 'content': ask})
    return _answer(turns, told, None, now, f'{kind.lower()} {what!r}')


def reply(message, now=None):
    """
    Answer what the boss wrote. Runs in the worker, from owner_line.answer().
    Returns what was said (for the log and the tests), or '' when nothing was.
    """
    turns, told = _history(message)
    if not turns:
        return ''
    _typing(message)
    return _answer(turns, told, message, now, f'message {message.pk}')


def _answer(turns, told, message, now, label):
    started = time.monotonic()
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
        logger.exception("Boss's line: Octos could not answer %s", label)
        _say(FAILED)
        return FAILED
    finally:
        logger.info("Boss's line: answered %s in %.1fs, looked up %s, tokens in %s (cached %s) out %s",
                    label, time.monotonic() - started, [c['name'] for c in calls],
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
        if message is not None and text and not acknowledged and len(text) <= ACK_LIMIT \
                and not checker.unverified(text, ''):
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
            # A photo from open_file is shown to the model as a picture, never kept as text.
            picture = result.pop('_image', None) if isinstance(result, dict) else None
            calls.append({'name': block.name, 'input': block.input, 'result': result})
            content = json.dumps(result, default=str)
            if picture:
                content = [{'type': 'text', 'text': content},
                           {'type': 'image', 'source': {'type': 'base64', 'media_type': picture[0],
                                                        'data': picture[1]}}]
            results.append({'type': 'tool_result', 'tool_use_id': block.id, 'content': content})
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
    if message is None or not message.external_id:
        return
    try:
        from apps.communications.services import whatsapp_client
        whatsapp_client.show_typing(message.external_id)
    except Exception:
        logger.debug('Typing indicator failed', exc_info=True)
