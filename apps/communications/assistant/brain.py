"""
The brain: reads a customer's message and decides what Octos says.

For one message: wait a moment (customers send several short messages
in a row; only the latest gets a run that answers), check the guards,
let the model read the conversation and call the tools, check every
figure in its reply, then act according to the mode:

  off     nothing happens and nothing is recorded (the kill switch)
  shadow  the reply is written into the thread as an internal note;
          the customer receives nothing
  live    the reply is sent; if the model asked for a person, the
          conversation is handed over too

Every run that gets past "off" is recorded in AssistantRun: why it was
silent, what it looked up, what it said, what was blocked and why, and
what it cost. In live mode, anything that goes wrong hands the
conversation to a person, so no customer is left waiting on a failure.
"""
import re
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.communications.assistant import checker, counter, prompt, tools
from apps.communications.models import AssistantRun, Conversation, Message

logger = logging.getLogger(__name__)

MODES = ('shadow', 'live')
MAX_ROUNDS = 5          # look-ups before Octos must answer
MAX_TOKENS = 1000        # replies are short by design
HISTORY = 20            # messages of context
ECHO_SECONDS = 5        # a message this soon after Octos's own is an auto-reply
LOOP_WINDOW = timedelta(minutes=10)
FAST_REPLIES = 2        # replies within ECHO_SECONDS of Octos's, in the window: an auto-reply
RUNAWAY_REPLIES = 15    # Octos replies in the window: a ceiling no human conversation reaches
SHADOW_PREFIX = 'Octos would say: '
# Sent when Octos can't safely answer (a blocked reply, a failure): no
# figures in it, so it can never be wrong, and the customer isn't left
# in silence while a person is brought in.
HOLDING = 'Let me check that with the team. Someone will get back to you shortly 🙏'
HOLDING_CLOSED = 'Let me check that with the team. Someone will get back to you as soon as we open 🙏'

# A message that only closes a conversation. After a statement it ends
# the conversation; after Octos's question ("Shall I send the link?") the
# same "ok" is an answer, so it is answered.
ACKNOWLEDGEMENTS = {
    'ok', 'okay', 'okk', 'oki', 'k', 'kk', 'noted', 'alright', 'sure', 'fine', 'cool', 'great',
    'thanks', 'thank you', 'thank u', 'thanks a lot', 'thx', 'tnx', 'ok thanks', 'okay thanks',
    'ok thank you', 'alright thanks', 'noted thanks', 'good night', 'goodnight', 'gn', 'bye',
    'bye bye', '👍', '🙏', '👌', '👍🏾', '🙏🏾', '👍🏽', '🙏🏽',
}
# A goodbye in more words (17 Nov 2026): "Thank you too" after a receipt got
# Octos asking about a file already printed. Every word one of these, and at
# least one of the core ones, and short: then it only closes the chat.
GOODBYE_WORDS = {
    'ok', 'okay', 'okk', 'oki', 'k', 'kk', 'noted', 'alright', 'sure', 'fine', 'cool', 'great',
    'thanks', 'thank', 'thankyou', 'tnx', 'thx', 'you', 'u', 'too', 'also', 'so', 'very', 'much', 'a', 'lot',
    'same', 'to', 'appreciated', 'appreciate', 'it', 'god', 'bless', 'boss', 'sir', 'madam', 'maam',
    'dear', 'bye', 'good', 'night', 'goodnight', 'gn', 'have', 'nice', 'day', 'evening', 'and',
    'well', 'done', 'received', 'got', 'perfect', 'with',
    # "You're welcome" after a receipt (24 Nov 2026) got a thank-you and a
    # request for her number.
    'youre', 'your', 'are', 'welcome', 'my', 'pleasure', 'most',
}
# "No please", "no thank you", "not now": a no to Octos's question (23 Nov 2026).
DECLINE_WORDS = {
    'no', 'nope', 'nah', 'please', 'pls', 'plz', 'thanks', 'thank', 'you', 'u', 'not', 'now', 'need',
    'its', 'it', 'is', 'fine', 'ok', 'okay', 'sir', 'madam', 'boss', 'dear', 'for', 'yet', 'again',
}
GOODBYE_CORE = {
    'ok', 'okay', 'okk', 'oki', 'k', 'kk', 'noted', 'alright', 'thanks', 'thank', 'thankyou', 'tnx', 'thx',
    'appreciated', 'appreciate', 'bye', 'goodnight', 'gn', 'received', 'perfect', 'welcome', 'pleasure',
}
TOOL_SPECS = [
    {
        'name': 'customer_declined_details',
        'description': ('Call when a customer says no to us saving their name or number. '
                        'Octos will not ask them again for 30 days.'),
        'input_schema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'branch_hours',
        'description': "Whether a branch is open now, today's hours or why it is closed, and when it "
                       'next opens. Leave branch out to get every branch you speak for.',
        'input_schema': {'type': 'object', 'properties': {
            'branch': {'type': 'string', 'description': 'Branch name, e.g. Westland.'},
        }},
    },
    {
        'name': 'customer_jobs',
        'description': "The open jobs of the customer you are talking to: what, which branch, stage, "
                       'promised time and balance due. It always looks up this customer; it takes no input.',
        'input_schema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'find_services',
        'description': 'Services matching what the customer asked for, each with its code, what its '
                       'price needs, and its add-ons (binding, lamination) with their codes.',
        'input_schema': {'type': 'object', 'properties': {
            'query': {'type': 'string'},
        }, 'required': ['query']},
    },
    {
        'name': 'quote',
        'description': 'The price of a service from the price list: service code, its specifications '
                       '(keys from its needs, e.g. pages, is_color, width_in, height_in), quantity, and '
                       'add-on codes. If something is missing, the result says what to ask for.',
        'input_schema': {'type': 'object', 'properties': {
            'service_code': {'type': 'string'},
            'specifications': {'type': 'object'},
            'quantity': {'type': 'integer', 'minimum': 1},
            'addon_codes': {'type': 'array', 'items': {'type': 'string'}},
        }, 'required': ['service_code']},
    },
    {
        'name': 'hand_to_person',
        'description': 'Bring in a person from the team, with a short reason they will see. Then tell '
                       'the customer kindly that someone will follow up shortly.',
        'input_schema': {'type': 'object', 'properties': {
            'reason': {'type': 'string'},
        }, 'required': ['reason']},
    },
    {
        'name': 'prepare_order',
        'description': "Create the order as agreed in this chat. Each line: service_code (from find_services), "
                       "quantity, specifications (the service's needs, e.g. width_in and height_in; pages come "
                       "from the file when one is given), addon_codes, and file: the number after 'file' in "
                       "[sent a document: ..., file 123]. Returns the order, itemised lines, total and ready time, "
                       "or why not (a missing or refused file, or a file warning the customer must accept). Set "
                       "accept_warnings only after the customer has said to go ahead despite the warning.",
        'input_schema': {'type': 'object', 'properties': {
            'lines': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'service_code': {'type': 'string'},
                'quantity': {'type': 'integer', 'minimum': 1},
                'specifications': {'type': 'object'},
                'addon_codes': {'type': 'array', 'items': {'type': 'string'}},
                'file': {'type': 'integer'},
            }, 'required': ['service_code']}},
            'accept_warnings': {'type': 'boolean'},
        }, 'required': ['lines']},
    },
    {
        'name': 'send_payment_link',
        'description': 'The Paystack link for an order you prepared in this chat. Only after the customer has '
                       'clearly agreed to the order and its total. Payment is in full.',
        'input_schema': {'type': 'object', 'properties': {
            'order': {'type': 'string', 'description': 'The order number prepare_order returned.'},
        }, 'required': ['order']},
    },
    {
        'name': 'keep_files',
        'description': ('The customer asked us to keep the files they sent for next time. We normally delete '
                        'customer files 14 days after they arrive; this keeps every file they have sent in this '
                        'chat until they ask us to delete them.'),
        'input_schema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'pay_at_counter',
        'description': ('For an order you prepared and the customer agreed to, when they would rather pay when '
                        'they collect at the counter instead of by the link. It goes to the front desk with a '
                        'pickup code: printed ahead for customers we know, otherwise printed when they arrive. '
                        'Front-desk work only; the tool says if part of it needs a deposit first.'),
        'input_schema': {'type': 'object', 'properties': {
            'order': {'type': 'string', 'description': 'The order number prepare_order returned.'},
        }, 'required': ['order']},
    },
    {
        'name': 'paper_sizes',
        'description': ("Paper sizes in plain words (A6 is a quarter of an A4 sheet, about postcard size), "
                        "how we print each one (smaller than A4 is printed on A4 and cut to size, priced as A4 "
                        "printing per sheet), how many fit on one A4 sheet and, with copies, how many A4 sheets "
                        "that takes. show_picture sends the customer a picture of the sizes drawn to scale "
                        "against an A4 sheet and a phone: use it when they ask what a size looks like or which "
                        "is bigger, and there is no photo of theirs to preview (then use print_preview)."),
        'input_schema': {'type': 'object', 'properties': {
            'sizes': {'type': 'array', 'items': {'type': 'string'},
                      'description': 'e.g. ["B6"], ["A5", "A6"], ["4 x 6"], ["half A4"]'},
            'copies': {'type': 'integer', 'minimum': 1},
            'show_picture': {'type': 'boolean'},
        }, 'required': ['sizes']},
    },
    {
        'name': 'what_is_this',
        'description': ("When a customer shows a photo, video or GIF of an item and asks whether we can do it, what "
                        "it is, or how much for something like it (the Can-Do Sandbox): first works out exactly "
                        "what it is (searching the web when needed), then whether Farhat can make it, how, a price "
                        "guide from our price list and a ready time, and what to ask them. files are the file "
                        "numbers from the chat; note is what they said about it. Not for a file they want printed "
                        "as it is."),
        'input_schema': {'type': 'object', 'properties': {
            'files': {'type': 'array', 'items': {'type': 'integer'}},
            'note': {'type': 'string'},
        }, 'required': ['files']},
    },
    {
        'name': 'print_preview',
        'description': ("Shows the customer how their own photo will print: the photo laid out on the sheet "
                        "at the size they chose (as many as fit, cut lines dotted in) and the piece they take "
                        "home, with a phone beside it for scale. Use it when they ask how it will look, or "
                        "once they've chosen a size for a photo. file is the photo's file number from the "
                        "chat. fill true trims the edges so the photo fills the piece; false keeps the whole "
                        "photo with white edges. Photos only (not PDFs or Word files)."),
        'input_schema': {'type': 'object', 'properties': {
            'file': {'type': 'integer'},
            'size': {'type': 'string', 'description': 'e.g. "A5", "B6", "4 x 6", "A4"'},
            'copies': {'type': 'integer', 'minimum': 1},
            'fill': {'type': 'boolean'},
        }, 'required': ['file', 'size']},
    },
    {
        'name': 'send_proforma',
        'description': "Issue a proforma (a formal quotation) for the lines agreed in this chat and send its "
                       "PDF here. Lines as for prepare_order (service_code, quantity, specifications with "
                       "pages or width_in/height_in, addon_codes), no files needed. Finds the customer's "
                       "record; if there is none it returns needs_customer_details, and you ask for exactly "
                       "that and call again with customer: first_name and last_name for a person, or "
                       "company_name and contact_person for a business. Returns the proforma number, "
                       "lines, total and the date it is valid until.",
        'input_schema': {'type': 'object', 'properties': {
            'lines': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'service_code': {'type': 'string'},
                'quantity': {'type': 'integer', 'minimum': 1},
                'specifications': {'type': 'object'},
                'addon_codes': {'type': 'array', 'items': {'type': 'string'}},
            }, 'required': ['service_code']}},
            'customer': {'type': 'object', 'properties': {
                'first_name': {'type': 'string'}, 'last_name': {'type': 'string'},
                'company_name': {'type': 'string'}, 'contact_person': {'type': 'string'},
            }},
        }, 'required': ['lines']},
    },
    {
        'name': 'use_phone_number',
        'description': ("Save the phone number a customer gave you, for a chat that has none (they use a "
                        "WhatsApp username, so WhatsApp hides their number). Only a number they typed in "
                        "this chat. Then carry on with the order or payment link."),
        'input_schema': {'type': 'object', 'properties': {
            'phone': {'type': 'string', 'description': 'As they wrote it, e.g. 024 400 0776.'},
        }, 'required': ['phone']},
    },
    {
        'name': 'save_customer_name',
        'description': ("Start a customer record for a chat whose number you just saved and that has no "
                        "record yet. Only the name they gave you in this chat."),
        'input_schema': {'type': 'object', 'properties': {
            'first_name': {'type': 'string'}, 'last_name': {'type': 'string'},
        }, 'required': ['first_name']},
    },
]


@dataclass
class Context:
    conversation: Conversation
    branches: list
    trigger: object = None
    handoff: str = ''
    calls: list = field(default_factory=list)


def respond(conversation_id, trigger_id=None, now=None):
    """Consider the customer's latest message. Returns the AssistantRun, or None when off."""
    mode = settings.OCTOS_ASSISTANT_MODE
    if mode not in MODES:
        return None

    now = now or timezone.now()
    conversation = Conversation.objects.get(pk=conversation_id)
    trigger = Message.objects.filter(pk=trigger_id).first() if trigger_id else None
    run = AssistantRun(conversation=conversation, trigger=trigger, mode=mode,
                       model=settings.OCTOS_ASSISTANT_MODEL)
    started = time.monotonic()

    try:
        silent = _silence(conversation, trigger, now)
        if silent:
            return _finish(run, AssistantRun.SKIPPED, started, reason=silent)

        # When to speak and when to wait (assistant/counter.py): counter
        # visits, a file with no words, a batch already acknowledged.
        counter_step = counter.step(conversation, trigger, now)
        if counter_step is not None:
            said, why = counter_step
            if said:
                _act(mode, conversation, run, text=said, handoff='')
                decision = AssistantRun.SHADOWED if mode == 'shadow' else AssistantRun.REPLIED
            else:
                decision = AssistantRun.SKIPPED
            return _finish(run, decision, started, reason=why, reply=said or '')

        automated = _looks_automated(conversation, now)
        if automated:
            if mode == 'live':
                from apps.communications.services import handover
                handover.octos_hands_over(conversation, automated)
            return _finish(run, AssistantRun.HANDED_OVER, started, reason=automated)

        from apps.organization.models import Branch
        ctx = Context(conversation, list(Branch.objects.filter(is_trading=True, is_active=True)), trigger)
        typing_since = _show_typing(trigger)
        reply = _converse(conversation, ctx, run)
        run.tool_calls = ctx.calls

        # A person may have stepped in while Octos was writing (17 Nov 2026).
        stepped_in = _stepped_in(conversation, trigger)
        if stepped_in:
            return _finish(run, AssistantRun.SKIPPED, started, reason=stepped_in, reply=reply)

        facts = json.dumps([c['result'] for c in ctx.calls], default=str) + _already_known(conversation, ctx, now)
        problems = checker.unverified(reply, facts)
        if problems:
            why = 'I could not verify ' + ', '.join(problems) + ' before sending.'
            _act(mode, conversation, run, text=_holding(), handoff=why, note=f'Octos blocked its own reply: {reply}')
            return _finish(run, AssistantRun.BLOCKED, started, reason=why, reply=reply)

        if not reply and not ctx.handoff:
            # Choosing silence (the customer was only closing the
            # conversation) is allowed: nothing is sent, nobody is called.
            return _finish(run, AssistantRun.SKIPPED, started, reason='Octos chose not to reply')

        _natural_pause(typing_since, trigger)
        # And once more after the pause: the last moment before it goes.
        stepped_in = _stepped_in(conversation, trigger)
        if stepped_in:
            return _finish(run, AssistantRun.SKIPPED, started, reason=stepped_in, reply=reply)
        _act(mode, conversation, run, text=reply, handoff=ctx.handoff)
        if mode == 'shadow':
            return _finish(run, AssistantRun.SHADOWED, started, reason=ctx.handoff, reply=reply)
        decision = AssistantRun.HANDED_OVER if ctx.handoff else AssistantRun.REPLIED
        return _finish(run, decision, started, reason=ctx.handoff, reply=reply)

    except Exception as exc:
        logger.exception('Octos failed on conversation %s', conversation_id)
        run.error = repr(exc)[:2000]
        if mode == 'live':
            try:
                from apps.communications.services import handover, whatsapp_outbound
                try:
                    run.sent = whatsapp_outbound.send_text(conversation, _holding())
                except Exception:
                    logger.exception('Octos could not send its holding reply on %s', conversation_id)
                handover.octos_hands_over(conversation, 'Octos hit a problem and could not answer.')
            except Exception:
                logger.exception('Octos could not hand over conversation %s', conversation_id)
        return _finish(run, AssistantRun.FAILED, started, reason='error')


# ── Guards ─────────────────────────────────────────────────────────────

def _stepped_in(conversation, trigger):
    """
    A reason not to send what Octos has just written, or None (17 Nov 2026).

    The guards below run before Octos starts; writing a reply takes several
    seconds, and a person who took over while the dots were showing still got
    Octos's reply sent over theirs. So this looks again, just before sending:
    a person has taken over, a person has replied, or the customer has written
    again (that newer message gets its own answer, with everything in view).
    """
    fresh = Conversation.objects.filter(pk=conversation.pk).values('handled_by', 'handoff_reason').first()
    if fresh and fresh['handled_by'] == Conversation.STAFF and not fresh['handoff_reason']:
        return 'a person took over while Octos was writing'
    if trigger is None:
        return None
    later = conversation.messages.filter(created_at__gt=trigger.created_at, is_internal_note=False)
    if later.filter(direction=Message.OUTBOUND, sent_by__isnull=False).exists():
        return 'a person replied while Octos was writing'
    if later.filter(direction=Message.INBOUND).exclude(kind__in=Message.QUIET_KINDS).exists():
        return 'the customer wrote again while Octos was writing; that message will be answered'
    return None


def files_handled(message):
    """Someone dealt with the files this message belongs to: claimed, opened or made into a job."""
    from apps.spine.models import Event as SpineEvent
    from apps.spine.obligations import batch_handled
    received = (SpineEvent.objects.select_related('visit')
                .filter(idempotency_key=f'wa:{message.external_id}').first())
    return bool(received and received.visit and batch_handled(received.visit, upto_event_id=received.pk))


def _website_case_note(conversation):
    """
    A customer who comes from the website's "Not sure what to ask for?" with
    their case number (SB-7K3QXA): Octos carries on from what it told them
    there, without asking them to explain again.
    """
    from apps.communications.models import SandboxCase
    recent = conversation.messages.filter(direction=Message.INBOUND).order_by('-created_at')[:4]
    codes = re.findall(r'\bSB-[A-Z2-9]{6}\b', ' '.join((m.body or '').upper() for m in recent))
    if not codes:
        return ''
    case = SandboxCase.objects.filter(code=codes[0]).first()
    if case is None or not case.result:
        return ''
    if case.conversation_id is None:
        SandboxCase.objects.filter(pk=case.pk).update(conversation=conversation)
    return ('The customer comes from the website, where they showed you a photo (case ' + case.code + '). What you '
            'told them there: ' + json.dumps(case.result, default=str) + '. Carry on from it: never ask them to '
            'explain again, and firm up the price with its questions.')


TAKEN_BACK_NOTE = (
    "A teammate had this chat and didn't get to reply, so you are picking it up for the team. Read the whole "
    "chat and carry on from exactly where it is, like someone who knows what's going on: if they have waited "
    "a while, a short sorry for the wait, then the next useful step. If a person opened their files, the team "
    "has seen them. Never ask what the chat already answers and never send a general check-in. If the chat "
    "shows nothing is left to do, reply with no text.")

FOLLOW_UP_NOTE = (
    "The customer sent a file from outside the shop and then went quiet for a while; nobody on the team has "
    "written to them since. Write one short follow-up that carries on from exactly where the chat is, about "
    "what they actually sent or asked (if you asked what they'd like done, ask again in different words, "
    "with the likely job as a suggestion; if a price is waiting on their yes, ask whether to go ahead). Sound "
    "like part of the team who knows the chat: never a general \"just checking in\". If the chat shows "
    "nothing is left open, reply with no text.")


def follow_up(conversation_id, now=None):
    """
    Octos follows up a quiet remote customer once, in his own words from the
    chat (quiet_remote.py, 20 Nov 2026). Returns the AssistantRun (REPLIED
    when something went out, SKIPPED when the chat needed nothing), or None
    when Octos is off or can't speak here.
    """
    mode = settings.OCTOS_ASSISTANT_MODE
    if mode not in MODES or not settings.ANTHROPIC_API_KEY:
        return None
    conversation = Conversation.objects.get(pk=conversation_id)
    if conversation.channel != Conversation.WHATSAPP or conversation.status == Conversation.SPAM \
            or conversation.handled_by != Conversation.OCTOS:
        return None
    trigger = (conversation.messages.filter(direction=Message.INBOUND, is_internal_note=False)
               .exclude(kind__in=Message.QUIET_KINDS).order_by('-created_at').first())
    if trigger is None:
        return None
    run = AssistantRun(conversation=conversation, trigger=trigger, mode=mode, model=settings.OCTOS_ASSISTANT_MODEL)
    started = time.monotonic()
    try:
        from apps.organization.models import Branch
        ctx = Context(conversation, list(Branch.objects.filter(is_trading=True, is_active=True)), trigger)
        reply = _converse(conversation, ctx, run, note=FOLLOW_UP_NOTE)
        run.tool_calls = ctx.calls
        if _stepped_in(conversation, trigger):
            return _finish(run, AssistantRun.SKIPPED, started, reason='follow-up: a person stepped in', reply=reply)
        facts = json.dumps([c['result'] for c in ctx.calls], default=str)
        if checker.unverified(reply, facts):
            return _finish(run, AssistantRun.SKIPPED, started, reason='follow-up: could not verify it', reply=reply)
        if not reply:
            return _finish(run, AssistantRun.SKIPPED, started, reason=FOLLOW_UP_NOTHING)
        _act(mode, conversation, run, text=reply, handoff='')
        decision = AssistantRun.SHADOWED if mode == 'shadow' else AssistantRun.REPLIED
        return _finish(run, decision, started, reason=FOLLOW_UP_REASON, reply=reply)
    except Exception as exc:
        logger.exception('Octos could not follow up conversation %s', conversation_id)
        run.error = repr(exc)[:2000]
        return _finish(run, AssistantRun.FAILED, started, reason='follow-up: error')


FOLLOW_UP_REASON = 'followed up a quiet customer'
FOLLOW_UP_NOTHING = 'follow-up: the chat needed nothing'


def taken_back_since(conversation, message):
    """Octos took this chat back from a silent person after this message arrived."""
    from apps.spine import kinds as spine_kinds
    from apps.spine.models import Event as SpineEvent
    return SpineEvent.objects.filter(conversation=conversation, kind=spine_kinds.OCTOS_TOOK_BACK,
                                     occurred_at__gte=message.created_at).exists()


def _silence(conversation, trigger, now):
    """A reason to stay silent, or None."""
    if not settings.ANTHROPIC_API_KEY:
        return 'no API key'
    if conversation.channel != Conversation.WHATSAPP:
        return 'not a WhatsApp conversation'
    if conversation.status == Conversation.SPAM:
        return 'marked spam'
    # Asking for a person doesn't mean Octos stops listening: until someone
    # actually takes over (the button, or replying), it keeps answering.
    if conversation.handled_by == Conversation.STAFF and not conversation.handoff_reason:
        return 'a person has taken over this conversation'
    if trigger is not None and trigger.kind == Message.REACTION:
        return 'a reaction needs no reply'
    if trigger is not None and trigger.kind == Message.UNSUPPORTED:
        return 'nothing WhatsApp passed on to read'
    visible = conversation.messages.filter(is_internal_note=False).order_by('-created_at')
    # A reaction (a thumbs-up on a receipt) is never the message waiting for
    # an answer: it neither starts a reply nor hides the question before it
    # (Henry, 13 Nov 2026).
    last = visible.filter(direction=Message.INBOUND).exclude(kind__in=Message.QUIET_KINDS).first()
    if last is None:
        return 'nobody is waiting for an answer'
    if trigger is not None and last.pk != trigger.pk:
        return 'a newer message will be answered instead'
    # A person handed back after this message: they dealt with it, sometimes
    # by a call Octos never sees (Kings Hub, 11 Nov 2026). Only what the
    # customer writes after the hand-back is Octos's to answer.
    from apps.spine import kinds as spine_kinds
    from apps.spine.models import Event as SpineEvent
    if SpineEvent.objects.filter(conversation=conversation, kind=spine_kinds.STAFF_HANDED_BACK,
                                 occurred_at__gte=last.created_at).exists():
        return 'a person dealt with this before handing it back'
    # Files someone already dealt with (claimed, opened, made into a job) need
    # no word from Octos: the work was done in person (11 Nov 2026). One of
    # the files just sent being opened is enough (20 Nov 2026): a person is
    # on it, even if an older file from the same visit was never opened.
    # Except when Octos took the chat back because nobody answered (20 Nov
    # 2026): then counter.step looks for proof the team dealt with it, and
    # Octos answers from the chat only when there is none.
    if last.media_id and not taken_back_since(conversation, last) and files_handled(last):
        return 'the files were already handled'
    # Answered already: by a person since, or by a run that saw this message.
    # Not "Octos spoke after it": a customer typing while Octos writes lands
    # messages just after its reply, unseen by it (Mercy, 6 Nov 2026).
    if visible.filter(direction=Message.OUTBOUND, sent_by__isnull=False,
                      created_at__gt=last.created_at).exists():
        return 'a person has answered'
    # A hand-over and a blocked reply both sent the customer a message, so
    # they count as answered too (Tailee got the same hand-over twice, 13 Nov 2026).
    if AssistantRun.objects.filter(conversation=conversation, trigger__created_at__gte=last.created_at,
                                   decision__in=[AssistantRun.REPLIED, AssistantRun.SHADOWED,
                                                 AssistantRun.HANDED_OVER, AssistantRun.BLOCKED]).exists():
        return 'already answered'
    before = visible.exclude(pk=last.pk).first()
    if _just_acknowledging(last, before):
        return 'the customer was only closing the conversation'
    return None


def _show_typing(trigger):
    """'typing...' for the customer, only in live mode, where a reply really follows. Returns when."""
    if settings.OCTOS_ASSISTANT_MODE != 'live' or trigger is None or not trigger.external_id:
        return None
    from apps.communications.services import whatsapp_client
    whatsapp_client.show_typing(trigger.external_id)
    return time.monotonic()


def show_typing_for(message_id):
    """
    On arrival, before the pause that lets a burst of messages land: the
    dots only if Octos would answer this message (the same guards as a
    run), so they never promise a reply that won't come.
    """
    message = Message.objects.select_related('conversation').filter(pk=message_id).first()
    if message is None or settings.OCTOS_ASSISTANT_MODE != 'live':
        return
    if _silence(message.conversation, message, timezone.now()) is None:
        _show_typing(message)

def _plain(message):
    """
    Lower case, spaces tidied, the closing dots gone, and a letter typed
    three or more times kept once: "Thank youuu" (Loretta, 24 Nov 2026) and
    "okkk" are "thank you" and "ok". No English word has a letter three
    times running, so nothing real is changed.
    """
    text = re.sub(r'\s+', ' ', re.sub(r'[\s.!]+$', '', (message.body or '').strip().lower()))
    return re.sub(r'([a-z])\1{2,}', r'\1', text)


def _only_emoji(text):
    """
    Emoji and nothing else ("🙏🏼🙏🏼🙏🏼"), never a wave: Emmanuel's praying
    hands after his receipt got "Hi 👋 How can I help you today?" (23 Nov 2026).
    """
    return bool(text) and not re.search(r'[\w?]', text) and '\U0001F44B' not in text


def _closing(message, before=None):
    """Only words of goodbye or thanks, or emoji alone once there is a chat to close."""
    text = _plain(message)
    return (text in ACKNOWLEDGEMENTS or _goodbye(text)
            or (before is not None and not message.media_id and _only_emoji(text)))


def _declining(message):
    words = re.findall(r"[a-z]+", _plain(message).replace("'", ''))
    return bool(words) and words[0] in ('no', 'nope', 'nah') and all(w in DECLINE_WORDS for w in words)


def _just_acknowledging(last, before):
    """'Ok' after a statement ends a conversation; after Octos's question it is an answer."""
    if not _closing(last, before):
        return False
    asked = (before is not None and before.direction == Message.OUTBOUND
             and (before.body or '').rstrip().endswith('?'))
    return not asked


def closed_after(recent):
    """
    The customer's last words (newest first in recent) close the chat:
    a goodbye after a statement, or a "no" to the question then a goodbye
    ("No please", "Thank you": Kwabena, 23 Nov 2026). A goodbye straight
    after a question is an answer, and a bare "no" waits for a word back.
    """
    run = []
    for message in recent:
        if message.direction != Message.INBOUND:
            break
        run.append(message)
    prior = recent[len(run)] if len(run) < len(recent) else None
    if not run or prior is None:
        return False
    if not _closing(run[0], prior):
        return False
    if not all(_closing(m, prior) or _declining(m) for m in run):
        return False
    oldest = run[-1]
    if _declining(oldest):
        return len(run) > 1
    return _just_acknowledging(oldest, prior)


def _goodbye(text):
    """'Thank you too', 'ok thanks boss', 'well received, God bless': only closing."""
    words = re.findall(r"[a-z]+", text.replace("'", ''))
    return (0 < len(words) <= 8 and all(w in GOODBYE_WORDS for w in words)
            and any(w in GOODBYE_CORE for w in words))


def _already_known(conversation, ctx, now):
    """
    Figures Octos may repeat without looking them up again in this run:
    today's hours at the trading branches, and the clock times Octos itself
    gave this customer in the last 12 hours (checked when they were sent).
    Prices are always looked up again: an order can change between turns.
    Loretta said "Yes please" to the payment link and was handed to a
    person instead, because the reply said 7:30pm, the closing time Octos
    had given her twenty minutes earlier from a lookup in another run
    (24 Nov 2026).
    """
    known = []
    for branch in ctx.branches:
        try:
            known.append(tools.branch_hours(branch, now))
        except Exception:
            logger.exception('Hours for the checker failed at branch %s', branch.pk)
    for body in (conversation.messages
                 .filter(direction=Message.OUTBOUND, sent_by__isnull=True, is_internal_note=False,
                         created_at__gte=now - timedelta(hours=12))
                 .values_list('body', flat=True)):
        known += sorted(checker._times(body))
    return ' ' + json.dumps(known, default=str)


def _holding():
    """The holding reply: 'shortly' while someone is in (open, or closing up), as everywhere else."""
    from apps.organization.services import shop_state
    someone_in = shop_state.any_branch() in (shop_state.OPEN, shop_state.CLOSING)
    return HOLDING if someone_in else HOLDING_CLOSED


def _looks_automated(conversation, now):
    """
    A reason a person should look (a possible bot loop), or None.

    A bot repeats itself: the same words coming back within seconds of
    Octos, more than once (an away message bouncing off Octos). Speed alone
    is not enough: a customer typing while Octos writes lands messages just
    after its reply (Mercy, 6 Nov 2026), and photos have no words to repeat.
    Only messages since the conversation last came back to Octos count.
    """
    since = now - LOOP_WINDOW
    if conversation.handled_since and conversation.handled_since > since:
        since = conversation.handled_since
    recent = list(conversation.messages.filter(is_internal_note=False, created_at__gte=since)
                  .order_by('created_at'))

    def from_octos(m):
        return m.direction == Message.OUTBOUND and m.sent_by_id is None and not m.kind

    if sum(1 for m in recent if from_octos(m)) >= RUNAWAY_REPLIES:
        return 'an unusually long run of replies in a few minutes; possibly an automatic reply'
    fast = [
        (after.body or '').strip().lower()
        for before, after in zip(recent, recent[1:])
        if from_octos(before) and after.direction == Message.INBOUND
        and after.message_type == Message.TEXT and (after.body or '').strip()
        and (after.created_at - before.created_at).total_seconds() <= ECHO_SECONDS
    ]
    if any(fast.count(words) >= FAST_REPLIES for words in set(fast)):
        return 'the same words arriving within seconds of Octos, more than once; possibly an automatic reply'
    return None


# ── Talking to the model ───────────────────────────────────────────────

def _converse(conversation, ctx, run, note=''):
    import anthropic

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    system = prompt.system_prompt(conversation, ctx.branches)
    # Regulars: on a 4th visit in 72 hours, ask once for their details (13 Nov 2026).
    from apps.communications.assistant import regulars
    # Picking up a chat a teammate never answered (20 Nov 2026).
    picking_up = TAKEN_BACK_NOTE if ctx.trigger is not None and taken_back_since(conversation, ctx.trigger) else ''
    for extra in (regulars.instruction(conversation), picking_up, _website_case_note(conversation), note):
        if extra:
            system = ((system + '\n\n' + extra) if isinstance(system, str)
                      else [*system, {'type': 'text', 'text': extra}])
    # The customer must speak last, or the model refuses (Steve, 14 Nov 2026).
    # Whatever Farhat sent after their latest message comes off the end and
    # is told to Octos as context instead.
    messages, sent_since = _split_trailing(_history(conversation))
    if not messages:
        return ''
    if sent_since:
        note = ("Since the customer's latest message, Farhat has already sent them the following. "
                "Don't repeat it; answer only what is still unanswered.\n" + sent_since)
        system = (system + '\n\n' + note) if isinstance(system, str) else [*system, {'type': 'text', 'text': note}]

    for round_number in range(MAX_ROUNDS):
        if round_number:
            # Looking things up takes a while: keep the dots showing.
            _show_typing(ctx.trigger)
        response = client.messages.create(
            model=settings.OCTOS_ASSISTANT_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOL_SPECS,
            messages=messages,
            # Automatic caching: the tools, instructions and conversation so
            # far are re-read from the cache on each later round, at a tenth
            # of the input price, instead of being sent again in full.
            cache_control={'type': 'ephemeral'},
        )
        usage = response.usage
        run.input_tokens += getattr(usage, 'input_tokens', 0) or 0
        run.output_tokens += getattr(usage, 'output_tokens', 0) or 0
        run.cache_read_tokens += getattr(usage, 'cache_read_input_tokens', 0) or 0
        run.cache_write_tokens += getattr(usage, 'cache_creation_input_tokens', 0) or 0

        if response.stop_reason == 'max_tokens':
            # Cut off mid-reply ("...10 p"): never sent. Fails the run, so the
            # customer gets the holding reply and a person is brought in.
            raise RuntimeError('Octos ran out of room mid-reply; a cut-off reply is never sent.')
        if response.stop_reason != 'tool_use':
            return ''.join(b.text for b in response.content if b.type == 'text').strip()

        messages.append({'role': 'assistant', 'content': response.content})
        results = []
        for block in response.content:
            if block.type != 'tool_use':
                continue
            try:
                result = _run_tool(block.name, block.input or {}, ctx)
            except Exception:
                logger.exception('Octos tool %s failed', block.name)
                result = {'error': 'That lookup failed.'}
            ctx.calls.append({'name': block.name, 'input': block.input, 'result': result})
            results.append({'type': 'tool_result', 'tool_use_id': block.id,
                            'content': json.dumps(result, default=str)})
        messages.append({'role': 'user', 'content': results})

    raise RuntimeError('Octos kept looking things up without answering')


def _run_tool(name, args, ctx):
    if name == 'branch_hours':
        wanted = (args.get('branch') or '').strip().lower()
        branches = [b for b in ctx.branches if not wanted or wanted in (b.name or '').lower()]
        if not branches:
            return {'error': f"Not a branch you speak for: {args.get('branch')}."}
        return [tools.branch_hours(b) for b in branches]
    if name == 'customer_jobs':
        return tools.customer_jobs(ctx.conversation.contact_phone)
    if name == 'find_services':
        return tools.find_services(args.get('query', ''))
    if name == 'quote':
        return tools.quote(
            args.get('service_code', ''), args.get('specifications') or {},
            args.get('quantity') or 1, args.get('addon_codes') or (), branches=ctx.branches,
        )
    # Before the order tools, or they run with no number and fail (Clarity,
    # 14 Nov 2026: "That lookup failed" twice, then a hand-over). This guard
    # sat below them from 9 Nov and was never reached.
    if name in ('prepare_order', 'send_payment_link', 'pay_at_counter') and not ctx.conversation.contact_phone:
        return {'error': 'needs_phone', 'say': ("This customer uses a WhatsApp username, so their number is "
                "hidden. Ask politely for the phone number they'd like for this order and its receipt, "
                "then save it with use_phone_number and try again.")}
    if name == 'prepare_order':
        from apps.communications.assistant import ordering
        return ordering.prepare_order(
            ctx.conversation, args.get('lines') or [],
            accept_warnings=bool(args.get('accept_warnings')), branches=ctx.branches,
        )
    if name == 'send_payment_link':
        from apps.communications.assistant import ordering
        return ordering.send_payment_link(ctx.conversation, str(args.get('order') or ''))
    if name == 'keep_files':
        from apps.communications.services.customer_files import keep_chat
        kept = keep_chat(ctx.conversation)
        return {'success': True, 'kept': kept,
                'say': 'Tell them warmly we will keep their files for next time, until they ask us to delete them.'}
    if name == 'pay_at_counter':
        from apps.communications.assistant import ordering
        return ordering.pay_at_counter(ctx.conversation, str(args.get('order') or ''))
    if name == 'use_phone_number':
        # Their number finds their customer record; with none, ask for a name (9 Nov 2026).
        from apps.communications.services import identity
        from apps.core.phones import to_international
        phone = to_international(str(args.get('phone') or ''))
        if not phone:
            return {'error': "That doesn't look like a phone number. Ask them kindly to check it."}
        customer = identity.match_phone(ctx.conversation, phone)
        if customer is not None:
            return {'saved': phone, 'found_their_record': customer.display_name,
                    'say': 'Thank them; you found their account. Carry on with what they wanted.'}
        return {'saved': phone, 'no_record': True,
                'say': ('Thank them. They have no account with us yet: ask kindly for at least their first '
                        'name (and surname if they like), then save it with save_customer_name.')}
    if name == 'save_customer_name':
        from apps.communications.services import identity
        first = str(args.get('first_name') or '').strip()
        if not first:
            return {'error': 'A first name is needed. Ask for it kindly.'}
        if ctx.conversation.customer_id:
            # Already known: the name they want is remembered for every greeting (20 Nov 2026).
            from apps.communications.services import names
            used = names.use_name(ctx.conversation, first)
            if not used:
                return {'error': "That doesn't read as a first name. Ask kindly what to call them."}
            return {'saved': used, 'say': f'Use {used} from now on.'}
        try:
            customer = identity.register_from_chat(ctx.conversation, first, str(args.get('last_name') or ''))
        except ValueError:
            return {'error': 'Ask for their phone number first, and save it with use_phone_number.'}
        return {'saved': customer.display_name, 'say': 'Thank them warmly: they are now known to us.'}
    if name == 'paper_sizes':
        return _paper_sizes(ctx, args)
    if name == 'print_preview':
        return _print_preview(ctx, args)
    if name == 'what_is_this':
        return _what_is_this(ctx, args)
    if name == 'send_proforma':
        from apps.communications.assistant import proformas
        return proformas.send_proforma(ctx.conversation, args.get('lines') or [], args.get('customer') or {})
    if name == 'customer_declined_details':
        # A "no thanks": Octos waits 30 days before asking again (regulars.py).
        from apps.spine import kinds
        from apps.spine.models import Event
        from apps.spine.recorder import record
        record(kinds.CUSTOMER_DECLINED_DETAILS, actor=Event.CUSTOMER, conversation=ctx.conversation,
               reason='Said no to saving their details.')
        return {'ok': True, 'say': 'Accept kindly. Do not ask again.'}
    if name == 'hand_to_person':
        ctx.handoff = args.get('reason') or 'Octos asked for a person.'
        return {'ok': True}
    return {'error': f'Unknown tool {name}.'}


def _paper_sizes(ctx, args):
    """
    Sizes in plain words, and the picture when asked (19 Nov 2026: a customer
    asked to see what B6 and A4 look like). The picture goes into the chat
    only when Octos is live; in shadow it is described, not sent.
    """
    from apps.communications.assistant import paper
    sizes = [str(s) for s in (args.get('sizes') or [])][:6]
    result = paper.facts(sizes, args.get('copies'))
    if not args.get('show_picture'):
        return result
    picture = paper.render(sizes)
    if picture is None:
        result['picture'] = 'None of these sizes is known, so no picture.'
        return result
    result['picture'] = _send_picture(ctx, picture, 'Drawn to scale, with a phone for size 📏', 'paper-sizes.png')
    return result


def _send_picture(ctx, picture, caption, filename):
    """A picture into the customer's chat, live only. Returns what to tell the model."""
    if settings.OCTOS_ASSISTANT_MODE != 'live':
        return 'Shadow mode: the picture would be sent here.'
    from apps.communications.services import whatsapp_outbound
    try:
        whatsapp_outbound.send_text(ctx.conversation, caption, image=picture, filename=filename)
    except Exception:
        logger.exception('Could not send %s', filename)
        return 'Could not be sent. Describe it in words instead.'
    return ('Sent in the chat just now, with the caption "' + caption + '". Don\'t repeat what the caption '
            'or the picture says; add only what they need next, in a line or two.')


def _what_is_this(ctx, args):
    """
    "Can you do this?" (the Can-Do Sandbox, 23 Nov 2026): what it is first,
    then whether Farhat can make it. Octos says "Let me take a look 👀"
    while it works, as a person would.
    """
    from apps.communications.models import SandboxCase
    from apps.communications.services import sandbox, whatsapp_outbound
    wanted = [int(f) for f in (args.get('files') or []) if str(f).isdigit()][:4]
    shown = list(ctx.conversation.messages.filter(pk__in=wanted, direction=Message.INBOUND).exclude(media_file=''))
    if not shown:
        return {'error': "Those aren't files this customer sent here, or they're still being saved."}
    files = []
    for m in shown:
        with m.media_file.open('rb') as handle:
            files.append((handle.read(), m.media_mime or ('image/jpeg' if m.message_type == Message.IMAGE else '')))
    try:
        if settings.OCTOS_ASSISTANT_MODE == 'live':
            whatsapp_outbound.send_text(ctx.conversation, 'Let me take a look 👀')
    except Exception:
        logger.warning('Sandbox: the "let me take a look" did not go', exc_info=True)
    case = SandboxCase.objects.create(source=SandboxCase.WHATSAPP, conversation=ctx.conversation,
                                      note=str(args.get('note') or '')[:500],
                                      files=[{'message': m.pk, 'mime': m.media_mime or ''} for m in shown])
    case = sandbox.run(case, files=files)
    r = dict(case.result)
    if case.status == SandboxCase.FAILED:
        return {'error': r.get('message') or "Couldn't look at it.", 'say': 'Ask them for a clearer photo.'}
    r['case'] = case.code
    r['say'] = {
        'yes': 'Tell them what it is, that we can make it, the price as a guide (a person confirms before they '
               'pay), the ready time, then ask its questions.',
        'partly': 'Say what it is, what we can and can\'t do of it, then the price guide and questions.',
        'no': "Say plainly we don't make this, and offer the nearest thing if there is one. Don't promise.",
        'unsure': "Say you're not sure what it is yet, ask its question, and that you've asked the team and will "
                  'come back to them.',
    }.get(r.get('can_do'), '')
    return r


def _print_preview(ctx, args):
    """
    Their own photo, laid out as it will print (19 Nov 2026). A tester asked
    "How would it look like??" and got a chart of paper sizes; what she
    meant was her photo.
    """
    from apps.communications.assistant import paper
    message = ctx.conversation.messages.filter(pk=args.get('file'), direction=Message.INBOUND).first()
    if message is None:
        return {'error': 'That file is not one this customer sent here.'}
    if not message.media_file:
        return {'error': 'The file is still being saved. Try again in a moment.'}
    if message.message_type != Message.IMAGE and not (message.media_mime or '').startswith('image/'):
        return {'error': 'A preview works for photos only. For a document, use paper_sizes to show the size.'}
    with message.media_file.open('rb') as handle:
        content = handle.read()
    picture, result = paper.preview(content, str(args.get('size') or ''), args.get('copies') or 1,
                                    bool(args.get('fill')))
    if picture is None:
        return result
    result['picture'] = _send_picture(ctx, picture, 'Here’s how it will print 👇', 'print-preview.png')
    return result


def _history(conversation):
    """The last messages as alternating turns, starting with the customer."""
    # In shadow mode Octos's replies are internal notes the customer never
    # saw; they still count as what Octos "said", or every earlier question
    # looks unanswered and gets answered again. Only in shadow: after
    # switching to live, notes the customer never received don't count.
    said = Q(is_internal_note=False) & ~Q(channel=Message.SYSTEM) & ~Q(kind__in=Message.QUIET_KINDS)
    if settings.OCTOS_ASSISTANT_MODE == 'shadow':
        said |= Q(is_internal_note=True, body__startswith=SHADOW_PREFIX)
    recent = list(
        conversation.messages.filter(said).order_by('-created_at')[:HISTORY]
    )[::-1]
    # Where this visit began: the last quiet gap of more than two hours (the
    # spine's own visit rule). Files from before it were for an earlier
    # request; on 17 Nov 2026 a file from the day before was priced together
    # with the day's new one. They stay in view, marked, so Octos can still
    # use one the customer asks for again.
    from apps.spine.visits import QUIET_GAP
    visit_starts = 0
    for i in range(len(recent) - 1, 0, -1):
        if recent[i].created_at - recent[i - 1].created_at > QUIET_GAP:
            visit_starts = i
            break
    # When the chat's files were dealt with: a job made from it, or a receipt
    # sent. A file before one of those has been printed or made into a job
    # (Miss, 16 Nov 2026: asked what to do with a portfolio already printed).
    done = sorted(list(conversation.jobs.values_list('created_at', flat=True))
                  + list(conversation.messages.filter(kind='receipt').values_list('created_at', flat=True)))
    turns = []
    for index, m in enumerate(recent):
        earlier = index < visit_starts
        role = 'user' if m.direction == Message.INBOUND else 'assistant'
        text = (m.body or '').strip()
        if m.is_internal_note:
            # "Octos would say: ..." without the prefix or the handover line.
            text = text[len(SHADOW_PREFIX):].split('\nOctos would hand')[0].strip()
        if m.media_id or m.message_type in (Message.IMAGE, Message.VIDEO, Message.DOCUMENT, Message.AUDIO):
            what = m.message_type.lower()
            if m.media_name:
                what += f': {m.media_name}'
            if m.media_pages:
                what += f", {m.media_pages} page{'s' if m.media_pages != 1 else ''}"
            info = m.media_info or {}
            if info.get('paper'):
                what += f", {info['paper']}"
            elif info.get('width_px') and info.get('height_px'):
                what += f", {info['width_px']} x {info['height_px']} px"
            if info.get('colour_mode'):
                what += ', black and white' if counter.is_grey(info['colour_mode']) else ', colour'
            if info.get('word'):
                what += ', a Word file'
            if m.file_deleted_at:
                # Deleted (25 Nov 2026): after 14 days, or because they asked.
                what += ', deleted from our storage, so we no longer have it: ask them to send it again if they want it printed'
            elif not m.media_file:
                what += ', not saved yet'
            else:
                what += f', file {m.pk}'
            if any(when > m.created_at for when in done):
                what += ', already dealt with: made into a job'
            if earlier:
                day = timezone.localtime(m.created_at).strftime('%a %d %b')
                what += f', sent on {day} in an earlier visit, not part of what they want now unless they ask for it again'
            text = (text + f' [sent a {what}]').strip()
        if index == visit_starts and visit_starts:
            when = timezone.localtime(m.created_at).strftime('%a %d %b, %H:%M')
            text = f'[A new visit began, {when}. Everything before this was an earlier visit.]\n{text}'.strip()
        if not text:
            continue
        if turns and turns[-1]['role'] == role:
            turns[-1]['content'] += '\n' + text
        else:
            turns.append({'role': role, 'content': text})
    while turns and turns[0]['role'] != 'user':
        turns.pop(0)
    return turns


def _split_trailing(turns):
    """
    (turns ending with the customer, what Farhat sent after them). A welcome,
    a receipt, or Octos's own reply to an earlier message that crossed this
    one can land after the customer's latest message; the model must not
    be asked with Farhat speaking last.
    """
    after = []
    while turns and turns[-1]['role'] == 'assistant':
        after.insert(0, turns.pop()['content'])
    return turns, '\n'.join(after)


# ── Acting ─────────────────────────────────────────────────────────────

def _act(mode, conversation, run, text, handoff, note=''):
    """Shadow writes a note; live sends and hands over."""
    from apps.communications.services import handover, whatsapp_outbound

    if mode == 'shadow':
        lines = [note or (f'{SHADOW_PREFIX}{text}' if text else 'Octos would stay silent.')]
        if handoff:
            lines.append(f'Octos would hand to a person: {handoff}')
        Message.objects.create(
            conversation=conversation, direction=Message.OUTBOUND, channel=Message.SYSTEM,
            message_type=Message.NOTE, is_internal_note=True, body='\n'.join(lines),
        )
        return

    if text:
        run.sent = whatsapp_outbound.send_text(conversation, text)
    if handoff:
        handover.octos_hands_over(conversation, handoff)


def _finish(run, decision, started, reason='', reply=''):
    """
    Every run ends here, whichever way it went: the one place its decision is
    written, to AssistantRun and to the spine, in the same transaction.
    """
    from django.db import transaction
    from apps.spine import kinds
    from apps.spine.models import Event
    from apps.spine.recorder import record

    run.decision = decision
    run.reason = (reason or '')[:300]
    run.reply = reply or run.reply
    run.duration_ms = int((time.monotonic() - started) * 1000)
    kind = {
        AssistantRun.REPLIED: kinds.OCTOS_REPLIED,
        AssistantRun.SKIPPED: kinds.OCTOS_STAYED_SILENT,
        AssistantRun.HANDED_OVER: kinds.OCTOS_HANDED_OVER,
        AssistantRun.SHADOWED: kinds.OCTOS_SHADOWED,
        AssistantRun.BLOCKED: kinds.OCTOS_BLOCKED,
        AssistantRun.FAILED: kinds.OCTOS_FAILED,
    }.get(decision)
    with transaction.atomic():
        run.save()
        if kind:
            conversation = run.conversation
            record(kind, actor=Event.OCTOS,
                   conversation=conversation, customer=conversation.customer,
                   key=f'run:{run.pk}',
                   payload={'run_id': run.pk, 'mode': run.mode, 'duration_ms': run.duration_ms,
                            'trigger_message_id': run.trigger_id},
                   reason=run.reason)
    return run



MIN_DOTS = 5      # seconds of 'typing...' before a reply, so it never lands unnaturally fast
DOTS_LAST = 20    # WhatsApp drops the dots after about 25 seconds: refresh before then


def _natural_pause(since, trigger):
    """At least a few seconds of dots before the reply, and dots still up when it lands."""
    if since is None:
        return
    elapsed = time.monotonic() - since
    if elapsed < MIN_DOTS:
        time.sleep(MIN_DOTS - elapsed)
    elif elapsed > DOTS_LAST:
        _show_typing(trigger)


# ── "Octos is writing" (9 Nov 2026) ───────────────────────────────────────
# While Octos works on a reply, the chat is marked writing in the shared cache
# and the portals are told at once; cleared when it's done, however it ends.
WRITING_SECONDS = 120


def _writing(conversation_id, on):
    try:
        from django.core.cache import cache
        key = f'octos_writing:{conversation_id}'
        cache.set(key, True, WRITING_SECONDS) if on else cache.delete(key)
        from apps.communications.live import announce
        announce(conversation_id)
    except Exception:
        logger.exception('Could not mark chat %s writing=%s', conversation_id, on)


_respond_unmarked = respond


LOCK_SECONDS = 180    # longer than any run; a crashed worker's lock expires by itself
RETRY_SECONDS = 10


def _still_reading(conversation_id):
    """
    A file sent in the last 3 minutes is still being measured. Never longer:
    a measurement that never finished must not hold Octos back for good.
    """
    from datetime import timedelta
    from django.utils import timezone
    return Message.objects.filter(
        conversation_id=conversation_id, direction=Message.INBOUND,
        created_at__gte=timezone.now() - timedelta(minutes=3), media_info__measuring=True,
    ).exists()


def respond(conversation_id, *args, **kwargs):
    """
    One run at a time per chat (14 Nov 2026). Two messages landing together
    each started a run and both answered. Now a run that finds another one
    working waits and tries again; by then the first has answered, and the
    guards in _silence see it.
    """
    from django.core.cache import cache
    if _still_reading(conversation_id):
        # A file just sent is openable but not yet measured (pages, paper):
        # Octos waits for it rather than answer half-informed (15 Nov 2026).
        from apps.communications.tasks import answer_whatsapp
        trigger_id = args[0] if args else kwargs.get('trigger_id')
        answer_whatsapp.apply_async((conversation_id, trigger_id), countdown=RETRY_SECONDS)
        return None
    key = f'octos_run:{conversation_id}'
    if not cache.add(key, True, LOCK_SECONDS):
        from apps.communications.tasks import answer_whatsapp
        trigger_id = args[0] if args else kwargs.get('trigger_id')
        answer_whatsapp.apply_async((conversation_id, trigger_id), countdown=RETRY_SECONDS)
        return None
    _writing(conversation_id, True)
    try:
        return _respond_unmarked(conversation_id, *args, **kwargs)
    finally:
        _writing(conversation_id, False)
        cache.delete(key)
