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

from apps.communications.assistant import checker, prompt, tools
from apps.communications.models import AssistantRun, Conversation, Message

logger = logging.getLogger(__name__)

MODES = ('shadow', 'live')
MAX_ROUNDS = 5          # look-ups before Octos must answer
MAX_TOKENS = 600        # replies are short by design
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
TOOL_SPECS = [
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

        automated = _looks_automated(conversation, now)
        if automated:
            if mode == 'live':
                from apps.communications.services import handover
                handover.octos_hands_over(conversation, automated)
            return _finish(run, AssistantRun.HANDED_OVER, started, reason=automated)

        from apps.organization.models import Branch
        ctx = Context(conversation, list(Branch.objects.filter(is_trading=True, is_active=True)), trigger)
        _show_typing(trigger)
        reply = _converse(conversation, ctx, run)
        run.tool_calls = ctx.calls

        facts = json.dumps([c['result'] for c in ctx.calls], default=str)
        problems = checker.unverified(reply, facts)
        if problems:
            why = 'I could not verify ' + ', '.join(problems) + ' before sending.'
            _act(mode, conversation, run, text=_holding(), handoff=why, note=f'Octos blocked its own reply: {reply}')
            return _finish(run, AssistantRun.BLOCKED, started, reason=why, reply=reply)

        if not reply and not ctx.handoff:
            # Choosing silence (the customer was only closing the
            # conversation) is allowed: nothing is sent, nobody is called.
            return _finish(run, AssistantRun.SKIPPED, started, reason='Octos chose not to reply')

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

def _silence(conversation, trigger, now):
    """A reason to stay silent, or None."""
    if not settings.ANTHROPIC_API_KEY:
        return 'no API key'
    if conversation.channel != Conversation.WHATSAPP:
        return 'not a WhatsApp conversation'
    if conversation.status == Conversation.SPAM:
        return 'marked spam'
    # Asking for a person doesn't mean Octos stops listening: until someone
    # actually takes over (the button, or replying), it keeps answering, so
    # a customer is never left in silence while they wait.
    if conversation.handled_by == Conversation.STAFF and not conversation.handoff_reason:
        return 'a person has taken over this conversation'

    visible = conversation.messages.filter(is_internal_note=False).order_by('-created_at')
    last = visible.first()
    if last is None or last.direction != Message.INBOUND:
        return 'nobody is waiting for an answer'
    if trigger is not None and last.pk != trigger.pk:
        return 'a newer message will be answered instead'

    before = visible.exclude(pk=last.pk).first()
    if (before is not None and before.direction == Message.OUTBOUND and before.sent_by_id is None
            and (last.created_at - before.created_at).total_seconds() <= ECHO_SECONDS):
        return 'looks like an automatic reply to Octos'
    if _just_acknowledging(last, before):
        return 'the customer was only closing the conversation'
    return None

def _show_typing(trigger):
    """'typing...' for the customer, only in live mode, where a reply really follows."""
    if settings.OCTOS_ASSISTANT_MODE != 'live' or trigger is None or not trigger.external_id:
        return
    from apps.communications.services import whatsapp_client
    whatsapp_client.show_typing(trigger.external_id)


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

def _just_acknowledging(last, before):
    """'Ok' after a statement ends a conversation; after Octos's question it is an answer."""
    text = re.sub(r'\s+', ' ', re.sub(r'[\s.!]+$', '', (last.body or '').strip().lower()))
    if text not in ACKNOWLEDGEMENTS:
        return False
    asked = (before is not None and before.direction == Message.OUTBOUND
             and (before.body or '').rstrip().endswith('?'))
    return not asked


def _holding():
    """The holding reply: 'shortly' only when a branch is open, as everywhere else."""
    from apps.organization.models import Branch
    from apps.organization.services import hours
    open_now = any(hours.is_open(b) for b in Branch.objects.filter(is_trading=True, is_active=True))
    return HOLDING if open_now else HOLDING_CLOSED


def _looks_automated(conversation, now):
    """
    A reason a person should look (a possible bot loop), or None.

    Judged by speed, not volume: a person needs more than a few seconds
    to read Octos's message and answer, an auto-reply doesn't. A busy
    human conversation (ten quick exchanges about an order) is normal and
    must never trip this. Only messages since the conversation last came
    back to Octos count, so a person handing back starts afresh.
    """
    since = now - LOOP_WINDOW
    if conversation.handled_since and conversation.handled_since > since:
        since = conversation.handled_since
    recent = list(
        conversation.messages.filter(is_internal_note=False, created_at__gte=since)
        .order_by('created_at')
    )

    def from_octos(m):
        return m.direction == Message.OUTBOUND and m.sent_by_id is None and not m.kind

    if sum(1 for m in recent if from_octos(m)) >= RUNAWAY_REPLIES:
        return 'an unusually long run of replies in a few minutes; possibly an automatic reply'
    fast = sum(
        1 for before, after in zip(recent, recent[1:])
        if from_octos(before) and after.direction == Message.INBOUND
        and (after.created_at - before.created_at).total_seconds() <= ECHO_SECONDS
    )
    if fast >= FAST_REPLIES:
        return 'replies arriving within seconds of Octos, more than once; possibly an automatic reply'
    return None


# ── Talking to the model ───────────────────────────────────────────────

def _converse(conversation, ctx, run):
    import anthropic

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    system = prompt.system_prompt(conversation, ctx.branches)
    messages = _history(conversation)

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
    if name == 'prepare_order':
        from apps.communications.assistant import ordering
        return ordering.prepare_order(
            ctx.conversation, args.get('lines') or [],
            accept_warnings=bool(args.get('accept_warnings')), branches=ctx.branches,
        )
    if name == 'send_payment_link':
        from apps.communications.assistant import ordering
        return ordering.send_payment_link(ctx.conversation, str(args.get('order') or ''))
    if name == 'hand_to_person':
        ctx.handoff = (args.get('reason') or 'Octos asked for a person.')[:200]
        return {'ok': True}
    return {'error': f'Unknown tool {name}.'}


def _history(conversation):
    """The last messages as alternating turns, starting with the customer."""
    # In shadow mode Octos's replies are internal notes the customer never
    # saw; they still count as what Octos "said", or every earlier question
    # looks unanswered and gets answered again. Only in shadow: after
    # switching to live, notes the customer never received don't count.
    said = Q(is_internal_note=False) & ~Q(channel=Message.SYSTEM)
    if settings.OCTOS_ASSISTANT_MODE == 'shadow':
        said |= Q(is_internal_note=True, body__startswith=SHADOW_PREFIX)
    recent = list(
        conversation.messages.filter(said).order_by('-created_at')[:HISTORY]
    )[::-1]
    turns = []
    for m in recent:
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
            if not m.media_file:
                what += ', not saved yet'
            else:
                what += f', file {m.pk}'
            text = (text + f' [sent a {what}]').strip()
        if not text:
            continue
        if turns and turns[-1]['role'] == role:
            turns[-1]['content'] += '\n' + text
        else:
            turns.append({'role': role, 'content': text})
    while turns and turns[0]['role'] != 'user':
        turns.pop(0)
    return turns


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
    run.decision = decision
    run.reason = (reason or '')[:300]
    run.reply = reply or run.reply
    run.duration_ms = int((time.monotonic() - started) * 1000)
    run.save()
    return run