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
LOOP_REPLIES = 4        # Octos replies in that window before a person is brought in
SHADOW_PREFIX = 'Octos would say: '
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
]


@dataclass
class Context:
    conversation: Conversation
    branches: list
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
        ctx = Context(conversation, list(Branch.objects.filter(is_trading=True, is_active=True)))
        reply = _converse(conversation, ctx, run)
        run.tool_calls = ctx.calls

        facts = json.dumps([c['result'] for c in ctx.calls], default=str)
        problems = checker.unverified(reply, facts)
        if problems:
            why = 'I could not verify ' + ', '.join(problems) + ' before sending.'
            _act(mode, conversation, run, text='', handoff=why, note=f'Octos blocked its own reply: {reply}')
            return _finish(run, AssistantRun.BLOCKED, started, reason=why, reply=reply)

        if not reply and not ctx.handoff:
            why = 'Octos had nothing to say.'
            _act(mode, conversation, run, text='', handoff=why)
            return _finish(run, AssistantRun.HANDED_OVER, started, reason=why)

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
                from apps.communications.services import handover
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
    if conversation.handled_by != Conversation.OCTOS:
        return 'a person has this conversation'

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
    return None


def _looks_automated(conversation, now):
    """A reason a person should look (a possible bot loop), or None."""
    recent = conversation.messages.filter(is_internal_note=False, created_at__gte=now - LOOP_WINDOW)
    octos = recent.filter(direction=Message.OUTBOUND, sent_by__isnull=True, kind='').count()
    if octos >= LOOP_REPLIES:
        return 'many replies back and forth in a few minutes; possibly an automatic reply'
    last_three = list(
        conversation.messages.filter(direction=Message.INBOUND)
        .order_by('-created_at').values_list('body', flat=True)[:3]
    )
    if len(last_three) == 3 and last_three[0] and len(set(last_three)) == 1:
        return 'the same message three times; possibly an automatic reply'
    return None


# ── Talking to the model ───────────────────────────────────────────────

def _converse(conversation, ctx, run):
    import anthropic

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    system = prompt.system_prompt(conversation, ctx.branches)
    messages = _history(conversation)

    for _ in range(MAX_ROUNDS):
        response = client.messages.create(
            model=settings.OCTOS_ASSISTANT_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOL_SPECS,
            messages=messages,
        )
        run.input_tokens += getattr(response.usage, 'input_tokens', 0) or 0
        run.output_tokens += getattr(response.usage, 'output_tokens', 0) or 0

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
            text = (text + f' [sent a {m.message_type.lower()}]').strip()
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