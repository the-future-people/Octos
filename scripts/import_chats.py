"""
Turn WhatsApp chat exports into anonymised conversations, with an index
to choose from.

Usage, from the repo root:
    python scripts/import_chats.py --branch kingshub --dry-run
    python scripts/import_chats.py --branch kingshub

Put the exports (the .zip files WhatsApp makes, or a bare .txt) in
docs/octos-voice/raw/. Everything this writes goes to raw/imported/,
which is git-ignored like the exports themselves.

Per chat, it:
  - reads the chat text out of the zip and never extracts the media
  - takes the customer to be the name in the export's file name
    ("WhatsApp Chat with Ama.zip") and calls everyone else Staff
  - strips phone numbers, emails, links, job/order codes and long
    references, and the customer's name wherever it appears
  - splits a long chat wherever it went quiet for days, since each
    conversation is a separate test
  - writes one file per conversation, plus index.md: one row each,
    to choose the best from without opening hundreds of files

Then read the ones worth keeping, rename them by topic, and move them
into docs/octos-voice/real/. Only those are committed. The script
catches most personal details, not all; reading is not optional.
"""
import argparse
import re
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / 'docs' / 'octos-voice' / 'raw'

# Invisible marks WhatsApp scatters through exports, and the odd spaces
# newer phones put before AM/PM.
INVISIBLE = dict.fromkeys(map(ord, '\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff'), None)
SPACES = dict.fromkeys(map(ord, '\u202f\u00a0'), ' ')

DATE = r'(?P<date>\d{1,2}[/.]\d{1,2}[/.]\d{2,4}),?\s+'
TIME = r'(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap]\.?\s?[Mm]\.?)?)'
# Android: 04/11/2026, 21:36 - Ama: hello
# iPhone:  [04/11/2026, 21:36:12] Ama: hello
MESSAGE = re.compile(r'^\[?' + DATE + TIME + r'\]?(?:\s-\s|\s)(?P<who>[^:]{1,60}):\s(?P<text>.*)$')
# A timestamped line with no sender: "Messages and calls are end-to-end
# encrypted", "Missed voice call"... skipped, never glued onto a message.
SYSTEM = re.compile(r'^\[?' + DATE + TIME + r'\]?(?:\s-\s|\s)')

MEDIA = re.compile(
    r'<Media omitted>|<attached:[^>]*>|\S+\s\(file attached\)'
    r'|\b(?:image|photo|video|audio|sticker|document|GIF)\s+omitted',
    re.IGNORECASE,
)
EMAIL = re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.]+\b')
LINK = re.compile(r'https?://\S+|www\.\S+|\b\S+\.(?:com|gh|app|net|org|io)\b\S*', re.IGNORECASE)
CODE = re.compile(r'\b(?:FP-[A-Z]{2,5}-\d{4}-\d+|ORD-\d{4}-\d+|[A-Z]{2,5}-\d{8}-\d{3,5})\b')
PHONE = re.compile(r'(?<![\w])\+?\d[\d\s-]{7,}\d(?![\w])')
LONG_REF = re.compile(r'\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{10,}\b')
# Mentions and social handles: @ama_prints.
HANDLE = re.compile(r'@[\w.]{2,}')
# Whatever the patterns above missed: any word holding 7+ digits in a row
# (a number glued to text, a file name like IMG_20250310_101530.jpg, a
# transaction id). Prices never reach 7 digits, so nothing real is lost.
GLUED = re.compile(r'\S*\d{7,}\S*')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--branch', default='', help='Where these chats came from, e.g. westland or kingshub')
    parser.add_argument('--staff', default='', help='Staff sender names, comma-separated, if detection fails')
    parser.add_argument('--gap-days', type=float, default=2, help='Quiet days that split a chat (default 2)')
    parser.add_argument('--min-messages', type=int, default=2, help='Skip conversations shorter than this (default 2)')
    parser.add_argument('--month-first', action='store_true', help='Dates are MM/DD (Ghana phones are DD/MM)')
    parser.add_argument('--out', default=str(RAW / 'imported'), help='Where to write (default: raw/imported, git-ignored)')
    parser.add_argument('--dry-run', action='store_true', help='Report only; write nothing')
    args = parser.parse_args()
    out = Path(args.out)

    sources = sorted(p for p in RAW.glob('*') if p.suffix.lower() in ('.zip', '.txt'))
    if not sources:
        print(f'No .zip or .txt exports in {RAW}')
        return

    chats = [(path, contact_of(path), parse(read_chat(path), args.month_first)) for path in sources]

    # A sender seen in more than one chat is the account's own side.
    seen = {}
    for _, _, (messages, _) in chats:
        for who in {m['who'] for m in messages}:
            seen[who] = seen.get(who, 0) + 1
    staff = {s.strip() for s in args.staff.split(',') if s.strip()}
    staff |= {who for who, count in seen.items() if count > 1}

    if not args.dry_run:
        out.mkdir(parents=True, exist_ok=True)
    number = next_number(out)
    rows = []
    for path, contact, (messages, orphans) in chats:
        senders = {m['who'] for m in messages}
        customer = {s for s in senders if same_person(s, contact)} or (senders - staff)
        if len(customer) != 1 or len(senders) > 3:
            print(f'SKIPPED {path.name}: could not tell the customer from staff (or a group chat).'
                  ' Rerun with --staff "Account name".')
            continue
        (customer,) = customer
        names = name_words(customer) | name_words(contact)

        kept = short = 0
        for episode in split(messages, args.gap_days):
            if len(episode) < args.min_messages or not any(m['who'] == customer for m in episode):
                short += 1
                continue
            target = out / f'{number:03d}-{(args.branch or "chat").lower()}.md'
            if not args.dry_run:
                target.write_text(render(episode, customer, names, args.branch), encoding='utf-8')
            rows.append(summary(target.name, episode, customer, names))
            number += 1
            kept += 1
        print(f'{path.name}: {len(messages)} messages, {orphans} unreadable,'
              f' {kept} conversation(s), {short} too short')

    if rows and not args.dry_run:
        write_index(out, rows)
    print(f'\n{len(rows)} conversation(s) {"to write" if args.dry_run else "written"} in {out}.'
          ' Choose from index.md; read before moving any into real/.')


def summary(name, episode, customer, names):
    mine = [m for m in episode if m['who'] == customer]
    first = clean(mine[0]['text'], names).replace('\n', ' ').replace('|', '/')
    media = sum(1 for m in episode if MEDIA.search(m['text']))
    return (name, len(episode), len(mine), moment(episode[0]['at']), media,
            first[:90] + ('…' if len(first) > 90 else ''))


def write_index(out, rows):
    lines = [
        '# Imported conversations',
        '',
        'One row per conversation. "From customer" counts their messages;',
        '"files" counts photos, documents and voice notes sent. Pick the',
        'ordinary and the instructive, read them, then move them into real/.',
        '',
        '| file | messages | from customer | when | files | customer opens with |',
        '|---|---|---|---|---|---|',
    ]
    lines += [f'| {n} | {total} | {theirs} | {when} | {media} | {first} |'
              for n, total, theirs, when, media, first in rows]
    (out / 'index.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def read_chat(path):
    if path.suffix.lower() == '.txt':
        return path.read_text(encoding='utf-8-sig', errors='replace')
    with zipfile.ZipFile(path) as z:
        texts = [n for n in z.namelist() if n.lower().endswith('.txt')]
        if not texts:
            return ''
        name = next((n for n in texts if 'chat' in n.lower()), max(texts, key=lambda n: z.getinfo(n).file_size))
        return z.read(name).decode('utf-8-sig', errors='replace')


def contact_of(path):
    """The customer's name from the export's file name, or ''."""
    match = re.search(r'WhatsApp Chat (?:with|-)\s*(.+)$', path.stem, re.IGNORECASE)
    return match.group(1).strip() if match else ''


def parse(text, month_first):
    """(messages, unreadable line count). Continuation lines join the message above."""
    messages, orphans = [], 0
    for raw in text.splitlines():
        line = raw.translate(INVISIBLE).translate(SPACES).rstrip()
        match = MESSAGE.match(line)
        if match:
            messages.append({
                'at': when(match['date'], match['time'], month_first),
                'who': match['who'].strip(),
                'text': match['text'].strip(),
            })
        elif SYSTEM.match(line):
            continue
        elif messages:
            if line.strip():
                messages[-1]['text'] += '\n' + line.strip()
        elif line.strip():
            orphans += 1
    return messages, orphans


def when(date, time, month_first):
    first, second, year = (int(p) for p in re.split(r'[/.]', date))
    year += 2000 if year < 100 else 0
    month, day = (first, second) if month_first else (second, first)
    clock = re.match(r'(\d{1,2}):(\d{2})', time)
    hour, minute = int(clock[1]), int(clock[2])
    marker = re.sub(r'[^APap]', '', time).upper()
    if marker == 'P' and hour < 12:
        hour += 12
    if marker == 'A' and hour == 12:
        hour = 0
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def split(messages, gap_days):
    episodes, current = [], []
    for m in messages:
        if current and m['at'] and current[-1]['at'] and \
                (m['at'] - current[-1]['at']).total_seconds() > gap_days * 86400:
            episodes.append(current)
            current = []
        current.append(m)
    if current:
        episodes.append(current)
    return episodes


def render(episode, customer, names, branch):
    lines = ['---', f'branch: {branch}', f'when: {moment(episode[0]["at"])}', 'topic:', '---']
    previous = None
    for m in episode:
        gap = pause(previous, m['at'])
        if gap:
            lines.append(f'*({gap})*')
        speaker = 'Customer' if m['who'] == customer else 'Staff'
        text = clean(m['text'], names).replace('\n', '\n  ')
        lines.append(f'{speaker}: {text}')
        previous = m['at'] or previous
    lines += ['---', 'Octos should: ', '']
    return '\n'.join(lines)


def clean(text, names):
    def media(match):
        t = match.group(0).lower()
        if any(k in t for k in ('video', '.mp4', '.mov')):
            return '[sends a video]'
        if any(k in t for k in ('audio', 'voice', '.opus', 'ptt-')):
            return '[sends a voice note]'
        if 'sticker' in t or '.webp' in t:
            return '[sends a sticker]'
        if any(k in t for k in ('document', '.pdf', '.doc', '.cdr', '.ai', '.psd', '.xls')):
            return '[sends a file]'
        if any(k in t for k in ('image', 'photo', '.jpg', '.jpeg', '.png', 'img-')):
            return '[sends a photo]'
        return '[sends a photo or file]'

    text = MEDIA.sub(media, text)
    text = EMAIL.sub('[email]', text)
    text = LINK.sub('[link]', text)
    text = CODE.sub('[code]', text)
    text = PHONE.sub('[number]', text)
    text = LONG_REF.sub('[ref]', text)
    text = HANDLE.sub('[handle]', text)
    text = GLUED.sub('[ref]', text)
    for word in names:
        text = re.sub(rf'\b{re.escape(word)}\b', '[name]', text, flags=re.IGNORECASE)
    return text


def name_words(name):
    """Words of a person's name worth hiding: letters only, 3 or more."""
    return {w for w in re.findall(r'[A-Za-z]+', name or '') if len(w) >= 3}


def same_person(sender, contact):
    if not contact:
        return False
    digits = re.sub(r'\D', '', contact)
    if len(digits) >= 9:
        return re.sub(r'\D', '', sender).endswith(digits[-9:])
    return sender.strip().lower() == contact.strip().lower()


def moment(at):
    if not at:
        return ''
    part = 'morning' if at.hour < 12 else 'afternoon' if at.hour < 17 else 'evening' if at.hour < 21 else 'night'
    return f'{at:%A} {part}'


def pause(before, after):
    """A note where time passed: '3 hours later', 'next day, 9:15am'."""
    if not before or not after:
        return ''
    if after.date() != before.date():
        days = (after.date() - before.date()).days
        label = 'next day' if days == 1 else f'{days} days later'
        return f'{label}, {after:%I:%M%p}'.replace(' 0', ' ').lower()
    hours = (after - before).total_seconds() / 3600
    return f'{int(hours)} hours later' if hours >= 2 else ''


def next_number(folder):
    used = [int(m[1]) for p in folder.glob('*.md') if (m := re.match(r'(\d{3})-', p.name))]
    return max(used, default=0) + 1


if __name__ == '__main__':
    main()