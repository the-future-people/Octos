"""
The Can-Do Sandbox engine (23 Nov 2026).

"Can you do this?" with a photo, a short video or a GIF. Two questions, in
this order, because the first must not be coloured by the second:

  1. What is it?  Octos looks, and searches the web when it needs to (a
     branded product, an unusual finish). Nothing of Farhat's yet.
  2. Can Farhat do it?  Only now our side: the catalogue (find_services),
     the price list (quote), the floor's ready time. Never a service or a
     price that isn't ours; a price only if quote gave it.

The customer watches four steps tick off (SandboxCase.STEPS), each with
what Octos found at that step. When Octos isn't sure, it says so, and the
boss is asked on his line; his answer is kept on the case, and similar
cases are put in front of Octos next time, so it answers like Farhat did.
"""
import base64
import io
import json
import logging
import re
import shutil
import subprocess
import tempfile

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_IMAGES = 6            # pictures shown to the model per look
IMAGE_SIDE = 1400
VIDEO_FRAMES = 6
SEARCHES = 3              # web searches allowed while identifying
TOOL_ROUNDS = 6

IDENTIFY = """\
You are identifying something a customer showed Farhat Printing Press, a print and branding shop \
in Accra, Ghana. Work out exactly what it is, before anything else: the kind of item, what it's made \
of, its finish, how it is used or mounted, and roughly how big. Look closely. If it is a branded or \
unusual product, or you are not sure, search the web to pin it down. Never guess about Farhat: that \
comes later.

Reply with only this JSON:
{"first_look": "what you see at a glance, under 12 words",
 "what": "what it is, in a customer's own words, under 14 words",
 "detail": "materials, finish, how it is mounted or used, one or two sentences",
 "made_how": "how items like this are usually made: method, materials, finishing",
 "size_guess": "for example about 60 x 40 cm, or empty",
 "quantity": number the customer mentioned, or null,
 "confidence": "high" or "medium" or "low",
 "is_print_file": true only if it is a document or design to print as it is, not an item to make,
 "question": "if confidence is low, the one question that would settle what it is; else empty"}"""

CAN_DO = """\
You are Octos at Farhat Printing Press, Westland, Accra. You are told what a customer's item is. Decide \
whether Farhat can make it, using only Farhat's own catalogue: find_services to search it, quote to price \
it. Never invent a service, a price or a time. A price only from a quote result: for a range, quote the \
smallest and largest likely size or quantity. If nothing in the catalogue makes it, say no, and the nearest \
thing Farhat can do if there is one. If you can't tell, say unsure.

Reply with only this JSON:
{"can_do": "yes" or "partly" or "no" or "unsure",
 "why": "one short line for the customer",
 "how": ["the steps in Farhat's terms, 2 to 5 short items"],
 "services": ["the service codes used"],
 "price_from": "GHS 0.00 from a quote, or null",
 "price_to": "GHS 0.00 from a quote, or null",
 "assumptions": "what the price assumes, e.g. about 60 x 40 cm, 1 piece",
 "ready": "the ready time from the quote, or empty",
 "questions": ["up to 3 questions that would firm up the price"],
 "nearest": "if no or partly: the nearest thing Farhat can do, or empty"}"""


# ── What the customer showed us ────────────────────────────────────────────

def _jpeg(content):
    from PIL import Image
    img = Image.open(io.BytesIO(content))
    img = img.convert('RGB')
    img.thumbnail((IMAGE_SIDE, IMAGE_SIDE))
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=82)
    return out.getvalue()


def _gif_frames(content, n=4):
    from PIL import Image, ImageSequence
    img = Image.open(io.BytesIO(content))
    frames = [f.copy() for f in ImageSequence.Iterator(img)]
    if not frames:
        return []
    picks = [frames[round(i * (len(frames) - 1) / max(1, n - 1))] for i in range(min(n, len(frames)))]
    out = []
    for f in picks:
        buf = io.BytesIO()
        f.convert('RGB').save(buf, 'PNG')
        out.append(_jpeg(buf.getvalue()))
    return out


def _video_frames(content, n=VIDEO_FRAMES):
    """Key frames from a short video, spread across it (ffmpeg). [] when it can't be read."""
    if not shutil.which('ffmpeg'):
        logger.warning('Sandbox: ffmpeg is not installed, a video was not read')
        return []
    with tempfile.TemporaryDirectory() as tmp:
        src = f'{tmp}/in'
        with open(src, 'wb') as fh:
            fh.write(content)
        try:
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of',
                                    'default=nw=1:nk=1', src], capture_output=True, text=True, timeout=30)
            duration = max(1.0, float(probe.stdout.strip() or 1))
            frames = []
            for i in range(n):
                at = duration * (i + 0.5) / n
                done = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{at:.2f}', '-i', src, '-frames:v', '1',
                                       '-f', 'image2', '-vcodec', 'mjpeg', 'pipe:1'],
                                      capture_output=True, timeout=30)
                if done.stdout:
                    frames.append(_jpeg(done.stdout))
            return frames
        except Exception:
            logger.warning('Sandbox: a video could not be read', exc_info=True)
            return []


def pictures(files):
    """
    The pictures Octos looks at, from what the customer showed: photos as
    they are, a GIF's frames, a video's key frames. files: [(bytes, mime)].
    """
    out = []
    for content, mime in files:
        mime = (mime or '').lower()
        try:
            if mime == 'image/gif':
                out += _gif_frames(content)
            elif mime.startswith('video/'):
                out += _video_frames(content)
            elif mime.startswith('image/'):
                out.append(_jpeg(content))
        except Exception:
            logger.warning('Sandbox: a file could not be read (%s)', mime, exc_info=True)
    return out[:MAX_IMAGES]


# ── The two questions ──────────────────────────────────────────────────────

def _client():
    import anthropic
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def _json(text):
    """The JSON object in the model's reply, or {}."""
    match = re.search(r'\{.*\}', text or '', re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except ValueError:
        return {}


def _text(response):
    return ''.join(getattr(b, 'text', '') for b in response.content if getattr(b, 'type', '') == 'text')


def identify(images, note=''):
    """Question one: what is it? With web search. Returns the identity dict."""
    content = [{'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg',
                                            'data': base64.b64encode(img).decode()}} for img in images]
    content.append({'type': 'text', 'text': f'The customer wrote: "{note}"' if note else 'The customer wrote nothing.'})
    messages = [{'role': 'user', 'content': content}]
    client = _client()
    search = [{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': SEARCHES,
               'user_location': {'type': 'approximate', 'city': 'Accra', 'country': 'GH',
                                 'timezone': 'Africa/Accra'}}]
    try:
        response = _identify_turns(client, messages, search)
    except Exception as exc:
        # The API refused the search (switched off for the account, a tool
        # version it won't take). Octos still has eyes: it judges from the
        # pictures alone, rather than the whole look failing.
        if getattr(exc, 'status_code', None) not in (400, 403, 404):
            raise
        logger.warning('Sandbox: web search refused, looking without it: %s', exc)
        response = _identify_turns(client, [{'role': 'user', 'content': content}], None)
    found = _json(_text(response))
    found['searched'] = any(getattr(b, 'type', '') == 'server_tool_use' for b in response.content)
    return found


def _identify_turns(client, messages, tools):
    """The identify call, carrying on when a long search pauses the turn."""
    extra = {'tools': tools} if tools else {}
    for _ in range(3):
        response = client.messages.create(model=settings.OCTOS_ASSISTANT_MODEL, max_tokens=1200, system=IDENTIFY,
                                          messages=messages, **extra)
        if response.stop_reason != 'pause_turn':
            break
        messages.append({'role': 'assistant', 'content': response.content})
    return response


def _money(value):
    """A price as the card shows it: 'GHS 45.00'. The model sometimes gives a bare number."""
    if value in (None, '', 0):
        return None
    if isinstance(value, (int, float)):
        return f'GHS {value:,.2f}'
    return str(value)


def _past_cases(identity, limit=5):
    """How Farhat answered similar things before: the boss's answers and the jobs that came of them."""
    from django.db.models import Q

    from apps.communications.models import SandboxCase
    words = [w for w in re.findall(r'[a-z]{4,}', (identity.get('what') or '').lower())][:6]
    if not words:
        return []
    match = Q()
    for w in words:
        match |= Q(result__what__icontains=w)
    from datetime import timedelta
    out = []
    for c in SandboxCase.objects.filter(match).select_related('job', 'conversation').order_by('-created_at')[:30]:
        job = c.job
        if job is None and c.conversation_id:
            # The job that came of it: made in that chat within three days of the look.
            job = (c.conversation.jobs.filter(created_at__gte=c.created_at,
                                              created_at__lte=c.created_at + timedelta(days=3))
                   .exclude(status__in=['CANCELLED', 'VOIDED']).order_by('created_at').first())
        if not (c.owner_answer or job):
            continue
        out.append({'what': c.result.get('what'), 'farhat_answered': c.owner_answer or None,
                    'job_made': (f'{job.title}, GHS {job.estimated_cost or 0:.2f}' if job else None)})
        if len(out) >= limit:
            break
    return out


def can_do(identity, note='', branches=()):
    """Question two: can Farhat make it, how, for how much, by when. Returns (answer, tool facts)."""
    from apps.communications.assistant import tools
    specs = [
        {'name': 'find_services', 'description': "Search Farhat's catalogue: services matching the words, with "
                                                 'their codes and what their price needs.',
         'input_schema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}},
        {'name': 'quote', 'description': 'The price of a service: code, specifications (keys from its needs, '
                                         'e.g. width_in, height_in, pages, is_color), quantity, add-on codes.',
         'input_schema': {'type': 'object', 'properties': {
             'service_code': {'type': 'string'}, 'specifications': {'type': 'object'},
             'quantity': {'type': 'integer', 'minimum': 1}, 'addon_codes': {'type': 'array', 'items': {'type': 'string'}}},
             'required': ['service_code']}},
    ]
    told = {'item': identity, 'customer_wrote': note, 'past_answers': _past_cases(identity)}
    messages = [{'role': 'user', 'content': json.dumps(told, default=str)}]
    facts = []
    client = _client()
    response = None
    for _ in range(TOOL_ROUNDS):
        response = client.messages.create(model=settings.OCTOS_ASSISTANT_MODEL, max_tokens=1200, system=CAN_DO,
                                          tools=specs, messages=messages)
        uses = [b for b in response.content if getattr(b, 'type', '') == 'tool_use']
        if not uses:
            break
        messages.append({'role': 'assistant', 'content': response.content})
        results = []
        for use in uses:
            args = use.input or {}
            try:
                if use.name == 'find_services':
                    out = tools.find_services(str(args.get('query') or ''))
                else:
                    out = tools.quote(str(args.get('service_code') or ''), args.get('specifications') or {},
                                      args.get('quantity') or 1, args.get('addon_codes') or (), branches)
            except Exception as exc:
                out = {'error': str(exc)[:200]}
            facts.append(out)
            results.append({'type': 'tool_result', 'tool_use_id': use.id, 'content': json.dumps(out, default=str)})
        messages.append({'role': 'user', 'content': results})
    return _json(_text(response)) if response is not None else {}, facts


def _checked_prices(answer, facts):
    """Prices only if a quote gave them (checker.py); otherwise none, and a person prices it."""
    from apps.communications.assistant.checker import unverified
    answer['price_from'], answer['price_to'] = _money(answer.get('price_from')), _money(answer.get('price_to'))
    said = ' '.join(filter(None, [answer.get('price_from'), answer.get('price_to')]))
    if said and unverified(said, json.dumps(facts, default=str)):
        logger.warning('Sandbox: dropped prices no quote gave: %s', said)
        answer['price_from'] = answer['price_to'] = None
        answer['assumptions'] = 'A person at Farhat will price this.'
    return answer


# ── A look, from start to finish ───────────────────────────────────────────

def _step(case, finding):
    case.stage = min(len(case.STEPS), case.stage + 1)
    case.findings = [*case.findings, finding or '']
    case.save(update_fields=['stage', 'findings', 'updated_at'])


def files_of(case):
    """The case's stored files, as [(bytes, mime)]."""
    from django.core.files.storage import default_storage
    out = []
    for f in case.files:
        try:
            with default_storage.open(f['path'], 'rb') as fh:
                out.append((fh.read(), f.get('mime', '')))
        except Exception:
            logger.warning('Sandbox: %s could not be opened', f.get('path'), exc_info=True)
    return out


def run(case, files=None):
    """
    Look at a case from start to finish, saving each step as it's done so
    the website can show it. Returns the case, DONE, UNSURE or FAILED.
    """
    from apps.communications.models import SandboxCase
    from apps.organization.models import Branch
    case.status = SandboxCase.RUNNING
    case.save(update_fields=['status', 'updated_at'])
    try:
        images = pictures(files if files is not None else files_of(case))
        if not images:
            case.status, case.error = SandboxCase.FAILED, 'Nothing we could look at.'
            case.result = {'message': "We couldn't open that file. Try a photo (JPG or PNG) or a short video."}
            case.save(update_fields=['status', 'error', 'result', 'updated_at'])
            return case
        identity = identify(images, case.note)
        _step(case, identity.get('first_look') or 'Taking a close look')
        _step(case, identity.get('what') or "Couldn't pin it down")
        branches = list(Branch.objects.filter(is_trading=True, is_active=True))
        if identity.get('is_print_file'):
            answer = {'can_do': 'yes', 'why': 'This is a design to print as it is.',
                      'how': ['Send it as a file on WhatsApp and we print it'], 'questions': [
                          'What size, and how many copies?']}
            facts = []
        elif identity.get('confidence') == 'low' and identity.get('question'):
            answer = {'can_do': 'unsure', 'why': "We're not sure what this is yet.", 'questions': [identity['question']]}
            facts = []
        else:
            answer, facts = can_do(identity, case.note, branches)
            answer = _checked_prices(answer, facts)
        _step(case, answer.get('why') or '')
        priced = ' to '.join(filter(None, [answer.get('price_from'), answer.get('price_to')]))
        _step(case, answer.get('assumptions') or (f'From {priced}' if priced else 'A person will confirm the price'))
        case.result = {
            'what': identity.get('what') or '', 'detail': identity.get('detail') or '',
            'confidence': identity.get('confidence') or 'medium', 'made_how': identity.get('made_how') or '',
            'size_guess': identity.get('size_guess') or '', 'quantity': identity.get('quantity'),
            'searched': bool(identity.get('searched')),
            'can_do': answer.get('can_do') or 'unsure', 'why': answer.get('why') or '',
            'how': answer.get('how') or [], 'services': answer.get('services') or [],
            'price_from': answer.get('price_from'), 'price_to': answer.get('price_to'),
            'assumptions': answer.get('assumptions') or '', 'ready': answer.get('ready') or '',
            'questions': (answer.get('questions') or [])[:3], 'nearest': answer.get('nearest') or '',
        }
        case.status = SandboxCase.UNSURE if case.result['can_do'] == 'unsure' else SandboxCase.DONE
        case.save(update_fields=['result', 'status', 'updated_at'])
        if case.status == SandboxCase.UNSURE and case.source != SandboxCase.STAFF:
            ask_the_boss(case, images[:1])      # never the boss about his own photo
        return case
    except Exception as exc:
        logger.exception('Sandbox case %s failed', case.code)
        case.status, case.error = SandboxCase.FAILED, repr(exc)[:2000]
        case.result = {'message': "Octos couldn't finish looking. Ask us on WhatsApp and a person will help."}
        case.save(update_fields=['status', 'error', 'result', 'updated_at'])
        return case


def ask_the_boss(case, images=()):
    """
    Octos isn't sure: the boss sees the photo and Octos's read on his line.
    When he answers the customer (send_to_customer / send_approved), his
    words are kept on the case (remember_answer).
    """
    from apps.communications.models import OwnerMessage
    from apps.communications.services import owner_line
    r = case.result
    who = case.conversation.display_name if case.conversation_id else 'A visitor on the website'
    body = (f'🔎 *Can we do this?* ({case.code})\n\n{who} showed me something and I\'m not sure.\n'
            f"_What I think it is:_ {r.get('what') or 'not clear'}\n{r.get('detail') or ''}\n\n"
            + ("Tell me what to say and I'll answer them." if case.conversation_id
               else 'They were on the website; if they continue on WhatsApp, I\'ll have this ready.'))
    card = None
    if images:
        try:
            from PIL import Image
            buf = io.BytesIO()
            Image.open(io.BytesIO(images[0])).save(buf, 'PNG')
            card = buf.getvalue()
        except Exception:
            card = None
    try:
        owner_line.tell(OwnerMessage.ANSWER, body, card=card, key=f'sandbox:{case.pk}', ref=f'sandbox:{case.pk}')
    except Exception:
        logger.warning('Sandbox: the boss could not be asked about %s', case.code, exc_info=True)


def remember_answer(conversation, words):
    """The boss's answer to a customer whose 'can you do this?' Octos wasn't sure about: kept for next time."""
    from datetime import timedelta

    from apps.communications.models import SandboxCase
    case = (SandboxCase.objects.filter(conversation=conversation, status=SandboxCase.UNSURE, owner_answer='',
                                       created_at__gte=timezone.now() - timedelta(days=3))
            .order_by('-created_at').first())
    if case is not None and words:
        case.owner_answer = words[:2000]
        case.save(update_fields=['owner_answer', 'updated_at'])
    return case


def for_customer(case):
    """The case as the website shows it (and as Octos hands it over on WhatsApp)."""
    return {
        'code': case.code, 'status': case.status, 'stage': case.stage, 'steps': case.STEPS,
        'findings': case.findings, 'result': case.result if case.status in ('DONE', 'UNSURE', 'FAILED') else None,
    }
