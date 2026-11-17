"""
python manage.py export_chats [--date 2026-11-16] [--print]

One day's chats in a single readable file, for reviewing how Octos did
(17 Nov 2026). For each chat, in order: what the customer sent (with what
Octos read from their files), what Octos and staff replied, every Octos run
(its decision, why, and the tools it used with what they returned), and the
moments that matter: a person taking over or handing back, a counter scan,
a job made or linked, a visit closing.

The file is saved to the private media bucket and a download link is printed
(it works for an hour). --print writes it here as well. Phone numbers are
shortened to their last four digits.

The day is the branch's day (Africa/Accra). Without --date: yesterday.
"""
import json
from datetime import datetime, time, timedelta

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

# Spine events worth a line; the rest repeat the messages and runs.
MOMENTS = {
    'staff.took_over': 'A person took over',
    'staff.handed_back': 'Handed back to Octos',
    'octos.took_back': 'Octos took it back (nobody answered)',
    'staff.reminded': 'Staff reminded: the customer waited 30 minutes',
    'conversation.resolved': 'Marked resolved',
    'presence.counter': 'At the counter',
    'counter.claimed': 'An attendant picked them up',
    'quote.given': 'Quote given',
    'payment.link_sent': 'Payment link sent',
    'payment.succeeded': 'Paid online',
    'job.created': 'Job made',
    'job.linked': 'Job linked to this chat',
    'visit.closed': 'Visit closed',
    'customer.registered': 'Customer registered',
    'customer.matched': 'Matched to a customer',
    'octos.asked_details': 'Octos asked for their details',
    'customer.declined_details': 'Declined to give details',
}
CLIP = 600   # the longest a tool result is shown


def short_phone(phone):
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    return f'…{digits[-4:]}' if digits else '—'


def clock(when):
    return timezone.localtime(when).strftime('%H:%M:%S')


def file_line(m):
    what = (m.message_type or 'file').lower()
    parts = [m.media_name or what]
    if m.media_pages:
        parts.append(f"{m.media_pages} page{'s' if m.media_pages != 1 else ''}")
    info = m.media_info or {}
    if info.get('paper'):
        parts.append(info['paper'])
    elif info.get('width_px') and info.get('height_px'):
        parts.append(f"{info['width_px']}x{info['height_px']}px")
    if info.get('colour_mode'):
        parts.append(f"colour mode {info['colour_mode']}")
    if not m.media_file:
        parts.append('not saved')
    return f"[{what}: {', '.join(str(p) for p in parts)}, file {m.pk}]"


def clip(value):
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= CLIP else text[:CLIP] + f'… ({len(text)} chars)'


class Command(BaseCommand):
    help = "Export one day's chats, with Octos's decisions, to a file for review."

    def add_arguments(self, parser):
        parser.add_argument('--date', help='YYYY-MM-DD, the branch day. Default: yesterday.')
        parser.add_argument('--print', action='store_true', help='Also write the export here.')

    def handle(self, *args, **opts):
        from apps.communications.models import AssistantRun, Conversation, Message
        from apps.spine.models import Event

        today = timezone.localdate()
        try:
            day = datetime.strptime(opts['date'], '%Y-%m-%d').date() if opts['date'] else today - timedelta(days=1)
        except ValueError:
            raise CommandError('Use --date YYYY-MM-DD, for example --date 2026-11-16.')
        start = timezone.make_aware(datetime.combine(day, time.min))
        end = start + timedelta(days=1)

        chat_ids = (Message.objects.filter(created_at__gte=start, created_at__lt=end)
                    .values_list('conversation_id', flat=True).distinct())
        chats = list(Conversation.objects.filter(pk__in=chat_ids))
        firsts = {c.pk: Message.objects.filter(conversation=c, created_at__gte=start, created_at__lt=end)
                  .order_by('created_at').values_list('created_at', flat=True).first() for c in chats}
        chats.sort(key=lambda c: firsts[c.pk])

        runs = AssistantRun.objects.filter(created_at__gte=start, created_at__lt=end, conversation__in=chats)
        tally = {}
        for decision in runs.values_list('decision', flat=True):
            tally[decision] = tally.get(decision, 0) + 1

        out = [
            f'# Chats on {day:%A %d %B %Y}',
            '',
            f'{len(chats)} chats. Octos runs: '
            + (', '.join(f'{k.lower().replace("_", " ")} {v}' for k, v in sorted(tally.items())) or 'none') + '.',
            'Phone numbers show their last four digits. Times are Accra time.',
            '',
        ]

        for n, chat in enumerate(chats, 1):
            out += self.chat(n, chat, start, end, Message, AssistantRun, Event)

        text = '\n'.join(out) + '\n'
        name = default_storage.save(f'exports/chats-{day:%Y-%m-%d}-{timezone.now():%H%M%S}.md',
                                    ContentFile(text.encode('utf-8')))
        if opts['print']:
            self.stdout.write(text)
        self.stdout.write(self.style.SUCCESS(f'{len(chats)} chats exported to {name}'))
        try:
            self.stdout.write(f'Download (works for an hour):\n{default_storage.url(name)}')
        except Exception:
            self.stdout.write('No download link here: run with --print and copy it instead.')

    def chat(self, n, chat, start, end, Message, AssistantRun, Event):
        # Never the full number as the name: a chat with no name shows only its last digits.
        who = (chat.customer.full_name if chat.customer_id else '') or chat.contact_name or 'No name'
        handle = f' @{chat.contact_username}' if chat.contact_username else ''
        lines = ['---', '', f'## {n}. {who}{handle} ({short_phone(chat.contact_phone)}), chat {chat.pk}', '']

        items = []
        for m in (Message.objects.filter(conversation=chat, created_at__gte=start, created_at__lt=end)
                  .select_related('sent_by').order_by('created_at')):
            items.append((m.created_at, 0, self.message(m)))
        for run in (AssistantRun.objects.filter(conversation=chat, created_at__gte=start, created_at__lt=end)
                    .order_by('created_at')):
            items.append((run.created_at, 1, self.run(run)))
        for e in (Event.objects.filter(conversation=chat, occurred_at__gte=start, occurred_at__lt=end,
                                       kind__in=MOMENTS).select_related('actor_user').order_by('occurred_at')):
            by = f' ({e.actor_user.full_name})' if e.actor_user_id else ''
            reason = f': {e.reason}' if e.reason else ''
            items.append((e.occurred_at, 2, f'{clock(e.occurred_at)}  ◆ {MOMENTS[e.kind]}{by}{reason}'))
        items.sort(key=lambda i: (i[0], i[1]))
        lines += [i[2] for i in items]
        lines.append('')
        return lines

    def message(self, m):
        from apps.communications.models import Message

        body = (m.body or '').strip()
        if m.media_id or m.message_type in (Message.IMAGE, Message.VIDEO, Message.DOCUMENT, Message.AUDIO):
            body = f'{body} {file_line(m)}'.strip()
        if m.is_internal_note or m.channel == Message.SYSTEM:
            who = 'Note'
        elif m.direction == Message.INBOUND:
            who = 'Customer'
        elif m.sent_by_id:
            who = m.sent_by.full_name
        else:
            who = 'Octos' if not m.kind or m.kind == 'text' else f'Octos ({m.kind})'
        body = body.replace('\n', '\n            ')
        status = f'  [{m.status.lower()}]' if m.direction == Message.OUTBOUND and m.status in ('FAILED',) else ''
        return f'{clock(m.created_at)}  {who}: {body or "(empty)"}{status}'

    def run(self, run):
        head = f'{clock(run.created_at)}  ⚙ Octos {run.decision.lower().replace("_", " ")}'
        if run.reason:
            head += f': {run.reason}'
        head += f'  ({run.duration_ms / 1000:.1f}s)'
        lines = [head]
        for call in run.tool_calls or []:
            lines.append(f'              tool {call.get("name")}({clip(call.get("input"))})')
            lines.append(f'                → {clip(call.get("result"))}')
        if run.error:
            lines.append(f'              error: {clip(run.error)}')
        return '\n'.join(lines)
