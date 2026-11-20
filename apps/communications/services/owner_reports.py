"""
What the owner's line reports (18 Nov 2026): the morning brief, the day's
close and "today so far". Each one gives:

  text     the report itself, as designed WhatsApp text (the default):
           a status line, dashed rules, figures lined up in fixed-width
           blocks, "Needs you" as quotes, emoji for colour
  card     the same report as plain data for the picture (owner_cards),
           sent when the owner replies "card"
  caption  the few words that go under the picture
  knock    one line for the template when WhatsApp's window is shut

Every figure comes from the Eye's own services (apps/eye/services), so the
owner's phone and the Eye can never disagree.
"""
import re
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

ZERO = Decimal('0')
DEAD = ('DRAFT', 'CANCELLED', 'VOIDED')
SHORT_METHODS = {'Mobile Money': 'MoMo', 'Paid Online': 'Online', 'Credit Account': 'Credit'}
LEVEL_ICON = {'red': '🔴', 'amber': '🟠', 'green': '🟢'}


def ghs(amount):
    return f'GHS {Decimal(amount or 0):,.2f}'


def amount(value):
    return f'{Decimal(value or 0):,.2f}'


def _day_name(day):
    return f'{day:%A} {day.day} {day:%B}'


def _short_day(day):
    return f'{day:%a} {day.day} {day:%b}'


# ── WhatsApp text, designed ────────────────────────────────────────────────

WIDTH = 24     # characters in a fixed-width line: fits the narrowest phone
# The dashed rule, in the same fixed-width font as the figures: exactly as wide
# as the tables on every phone (an iPhone drew '┄' three times wider and
# wrapped it, 18 Nov 2026).
RULE = '```' + '-' * WIDTH + '```'


def table(rows, width=WIDTH):
    """
    Rows lined up in a fixed-width block: labels left, values right. Every
    block is the same width, so the figures line up down the whole message.
    A long label is shortened rather than pushing its value off the edge.
    """
    lines = []
    for label, value in rows:
        label, value = str(label), str(value)
        room = max(width - len(value) - 2, 4)
        if len(label) > room:
            label = label[:room - 1] + '…'
        lines.append(label + ' ' * max(width - len(label) - len(value), 2) + value)
    return '```' + '\n'.join(lines) + '```' if lines else ''


CODES = re.compile(r'\b((?:FP|PFI|JOB)-[A-Z0-9]+(?:-[A-Za-z0-9]+)+)')


def chips(words):
    """Job and proforma numbers as grey chips: readable, and never a phone link."""
    return CODES.sub(lambda m: f'`{m.group(1)}`', str(words))


def hero(label, value, note):
    """
    The big number, with room around it (18 Nov 2026): the label, the amount
    in bold, the change in light italics under it, then a blank line before
    the figures. WhatsApp has no text sizes; italics without an emoji is the
    quietest it gets.
    """
    lines = [label, f'*{value}*']
    if note:
        lines.append(f'_{note}_')
    return '\n'.join(lines) + '\n'


def needs_you_text(items, limit=5):
    if not items:
        return '🟢 *Nothing needs you right now*'
    worst = 'red' if any(level == 'red' for level, _ in items) else 'amber'
    lines = [f'{LEVEL_ICON[worst]} *Needs you*']
    lines += [f'> {chips(words)}' for _, words in items[:limit]]
    if len(items) > limit:
        lines.append(f'> and {len(items) - limit} more')
    return '\n'.join(lines)


def compose(*parts):
    """Join the parts that exist, one per line."""
    return '\n'.join(p for p in parts if p)


def _change(now, before, against):
    from apps.eye.services import periods
    pct = periods.change(now, before)
    if pct is None:
        return ''
    if pct == 0:
        return f'Same as {against}'
    return f'{"▲" if pct > 0 else "▼"} {abs(pct)}% on {against}'


def _company():
    from apps.eye.services import scope
    return scope.resolve('company')


def _owner_name():
    from apps.accounts.models import CustomUser
    owner = CustomUser.objects.filter(is_business_owner=True, is_active=True).order_by('pk').first()
    return (owner.first_name if owner else '') or 'boss'


# ── The figures ────────────────────────────────────────────────────────────

def money_for(ids, start, end):
    """(collected, [(method label, count, amount)]), biggest first."""
    from apps.eye.services import money
    from apps.finance.payment_methods import BY_CODE
    collected = money.collected(ids, start, end)
    methods = []
    for code, row in sorted(money.by_method(ids, start, end).items(), key=lambda kv: -kv[1]['amount']):
        label = BY_CODE[code].label if code in BY_CODE else (code or 'Other').title()
        methods.append((label, row['count'], row['amount']))
    return collected, methods


def _method_rows(methods):
    return [(f'{label} · {n}', ghs(a)) for label, n, a in methods]


def _method_table(methods):
    return table([(f'{SHORT_METHODS.get(label, label)} · {n}', amount(a)) for label, n, a in methods])


def jobs_for(ids, start, end):
    from apps.eye.services import jobs
    kept_pct, kept, broken = jobs.promise_kept(ids, start, end)
    return {
        'taken': jobs.taken(ids, start, end).count(),
        'finished': jobs.finished(ids, start, end),
        'kept_pct': kept_pct, 'kept': kept, 'broken': broken,
    }


def _kept(j):
    return f"{j['kept_pct']}%" if j['kept_pct'] is not None else '–'


def _jobs_table(j):
    return table([('Jobs taken', j['taken']), ('Finished', j['finished']), ('Promises kept', _kept(j))])


def discounts_for(start, end):
    """Price cuts that took effect in the window: (count, total off, [(number, amount, reason)])."""
    from apps.jobs.models import PriceCut
    cuts = (PriceCut.objects.filter(status=PriceCut.Status.APPLIED)
            .filter(Q(decided_at__gte=start, decided_at__lt=end)
                    | Q(decided_at__isnull=True, created_at__gte=start, created_at__lt=end))
            .select_related('job', 'proforma').order_by('created_at'))
    total, rows = ZERO, []
    for c in cuts:
        total += c.amount or ZERO
        what = c.job.job_number if c.job_id else c.proforma.proforma_number
        rows.append((what, c.amount or ZERO, c.reason))
    return len(rows), total, rows


def cash_for(ids, day):
    """Each cashier's sign-off for the day: ([(name, variance)], total short)."""
    from apps.finance.models import CashierFloat
    floats = (CashierFloat.objects.filter(daily_sheet__branch_id__in=ids, daily_sheet__date=day,
                                          is_signed_off=True)
              .select_related('cashier'))
    rows, short = [], ZERO
    for f in floats:
        v = f.variance or ZERO
        if v < 0:
            short += -v
        rows.append((f.cashier, v))
    return rows, short


def _variance_words(v, money=ghs):
    if abs(v) < Decimal('0.01'):
        return 'Balanced'
    return f'Short {money(-v)}' if v < 0 else f'Over {money(v)}'


def needs_you(day):
    """The Eye's alerts plus price cuts waiting: [(level, words)], most serious first."""
    from apps.eye.services import alerts
    from apps.jobs.models import PriceCut
    out = []
    waiting = PriceCut.objects.filter(status=PriceCut.Status.PENDING).count()
    if waiting:
        out.append(('red', f'{waiting} discount{"s" if waiting > 1 else ""} waiting for your OK'))
    for a in alerts.compute(_company(), day):
        where = f' · {a["where"]}' if a['where'] and a['where'] != 'Westland Branch' else ''
        out.append((a['level'], f'{a["title"]}{where}'))
    return out


def due_on(ids, day):
    from apps.eye.services import periods
    from apps.jobs.models import Job
    start, end = periods.bounds(day, day)
    return (Job.objects.filter(branch_id__in=ids, estimated_ready_at__gte=start, estimated_ready_at__lt=end)
            .exclude(status__in=DEAD).exclude(work_state='DONE').exclude(handover_state='HANDED_OVER')
            .count())


def branch_rows(sc, start, end):
    """Money per branch, only when there is more than one branch with money."""
    from apps.eye.services import money
    from apps.organization.models import Branch
    rows = []
    for b in Branch.objects.filter(pk__in=sc.branch_ids).order_by('name'):
        collected = money.collected((b.pk,), start, end)
        if collected:
            rows.append((b.name.replace(' Branch', ''), collected))
    return rows if len(rows) > 1 else []


def _machines(ids):
    from apps.production.models import Machine
    ms = Machine.objects.filter(branch_id__in=ids, is_active=True)
    return ms.filter(is_available=True).count(), ms.count()


def _owed(ids):
    from apps.eye.services import money
    o = money.owed(ids)
    return o['job_balances'] + o['credit_owed']


def _alert_section(items, limit=6):
    if not items:
        return {'title': 'Needs you', 'items': [('green', 'Nothing needs you right now')]}
    extra = len(items) - limit
    shown = items[:limit] + ([('amber', f'and {extra} more')] if extra > 0 else [])
    return {'title': 'Needs you', 'items': shown}


def _alert_words(items, limit=3):
    if not items:
        return 'Nothing needs you right now.'
    return 'Needs you: ' + '; '.join(words for _, words in items[:limit]) + ('…' if len(items) > limit else '.')


# ── The three reports ──────────────────────────────────────────────────────

def brief(day=None, greeting=None):
    """
    Before opening: yesterday in numbers, and what today holds. greeting,
    when given, opens it instead of the plain "Good morning": the 7:30 brief
    opens with the time and the weather (20 Nov 2026); a brief asked for
    later in the day keeps the plain heading.
    """
    from apps.eye.services import periods
    day = day or timezone.localdate()
    yday, before = day - timedelta(days=1), day - timedelta(days=2)
    sc = _company()
    ids = sc.branch_ids
    start, end = periods.bounds(yday, yday)
    p_start, p_end = periods.bounds(before, before)
    collected, methods = money_for(ids, start, end)
    prev, _ = money_for(ids, p_start, p_end)
    note = _change(collected, prev, f'{before:%A}')
    j = jobs_for(ids, start, end)
    n_cuts, off, _ = discounts_for(start, end)
    due = due_on(ids, day)
    up, total = _machines(ids)
    owed = _owed(ids)
    alerts = needs_you(day)
    branches = branch_rows(sc, start, end)
    name = _owner_name()

    today_rows = [('Jobs due', due), ('Machines up', f'{up} of {total}')]
    if owed:
        today_rows.append(('Owed to us', amount(owed)))
    if n_cuts:
        today_rows.append((f'Discounts · {n_cuts}', amount(off)))

    text = compose(
        greeting or f'☀️ *Good morning, {name}*',
        f'_Morning brief · {_short_day(day)}_',
        RULE,
        hero('Collected yesterday', ghs(collected), note),
        _jobs_table(j),
        RULE,
        methods and '💳 *How it was paid* · GHS',
        methods and _method_table(methods),
        branches and '🏢 *By branch* · GHS',
        branches and table([(b, amount(a)) for b, a in branches]),
        '📅 *Today*',
        table(today_rows),
        RULE,
        needs_you_text(alerts),
        RULE,
        'Reply *today* or *card* any time',
    )

    sections = []
    if methods:
        sections.append({'title': 'How it was paid', 'rows': _method_rows(methods)})
    if branches:
        sections.append({'title': 'By branch', 'rows': [(b, ghs(a)) for b, a in branches]})
    sections.append({'title': 'Today', 'rows': [(a if a != 'Owed to us' else 'Still owed to us',
                                                 f'GHS {b}' if a.startswith(('Owed', 'Discounts')) else str(b))
                                                for a, b in today_rows]})
    sections.append(_alert_section(alerts))
    card = {
        'kicker': 'Morning brief', 'date': _day_name(day),
        'greeting': f'Good morning, {name}',
        'hero': {'label': f'Collected yesterday, {_short_day(yday)}', 'value': ghs(collected), 'note': note},
        'tiles': [('Jobs taken', str(j['taken'])), ('Finished', str(j['finished'])), ('Promises kept', _kept(j))],
        'sections': sections,
        'footer': 'Reply "today" any time for the latest',
    }
    caption = (f'☀️ Good morning, {name}. Yesterday {ghs(collected)} collected; '
               f'{due} job{"s" if due != 1 else ""} due today.')
    knock = (f'Your morning brief for {_short_day(day)} is ready. Yesterday {ghs(collected)} collected, '
             f'{due} jobs due today.')
    return {'text': text, 'card': card, 'caption': caption, 'knock': knock}


def close(day=None):
    """After sign-off: the day in full."""
    from apps.eye.services import periods
    day = day or timezone.localdate()
    yday = day - timedelta(days=1)
    sc = _company()
    ids = sc.branch_ids
    start, end = periods.bounds(day, day)
    p_start, p_end = periods.bounds(yday, yday)
    collected, methods = money_for(ids, start, end)
    prev, _ = money_for(ids, p_start, p_end)
    note = _change(collected, prev, 'yesterday')
    j = jobs_for(ids, start, end)
    n_cuts, off, cuts = discounts_for(start, end)
    cash, short = cash_for(ids, day)
    alerts = needs_you(day)
    branches = branch_rows(sc, start, end)

    cut_lines = [f'> {chips(what)} {amount(a)} · {reason}' for what, a, reason in cuts[:5]]
    text = compose(
        f'🌙 *Day close · {_short_day(day)}*',
        '_Here is how today went_',
        RULE,
        hero('Collected today', ghs(collected), note),
        _jobs_table(j),
        RULE,
        methods and '💳 *How it was paid* · GHS',
        methods and _method_table(methods),
        branches and '🏢 *By branch* · GHS',
        branches and table([(b, amount(a)) for b, a in branches]),
        cash and '💵 *Cash at sign-off*',
        cash and table([(c.first_name or c.full_name, _variance_words(v, amount).lower()) for c, v in cash]),
        n_cuts and f'🏷️ *Discounts* · {n_cuts} · {ghs(off)} off',
        '\n'.join(cut_lines),
        RULE,
        needs_you_text(alerts),
        RULE,
        'Good night from Octos 🐙',
    )

    sections = []
    if methods:
        sections.append({'title': 'How it was paid', 'rows': _method_rows(methods)})
    if branches:
        sections.append({'title': 'By branch', 'rows': [(b, ghs(a)) for b, a in branches]})
    if cash:
        sections.append({'title': 'Cash at sign-off', 'rows': [(c.full_name, _variance_words(v)) for c, v in cash]})
    if n_cuts:
        sections.append({'title': f'Discounts · {n_cuts} · {ghs(off)} off',
                         'items': [('amber', f'{what}: {ghs(a)} off · {reason}') for what, a, reason in cuts[:5]]})
    sections.append(_alert_section(alerts))
    card = {
        'kicker': 'Day close', 'date': _day_name(day),
        'greeting': 'Here is how today went',
        'hero': {'label': 'Collected today', 'value': ghs(collected), 'note': note},
        'tiles': [('Jobs taken', str(j['taken'])), ('Finished', str(j['finished'])), ('Promises kept', _kept(j))],
        'sections': sections,
        'footer': 'Good night from Octos',
    }
    caption = f'🌙 Today: {ghs(collected)} collected.' + (f' Cash short {ghs(short)}.' if short else '')
    knock = f'Your day close for {_short_day(day)} is ready. {ghs(collected)} collected today.'
    return {'text': text, 'card': card, 'caption': caption, 'knock': knock}


def snapshot(now=None):
    """Today so far, whenever the owner asks."""
    from apps.eye.services import periods
    now = now or timezone.now()
    day = timezone.localdate(now)
    sc = _company()
    ids = sc.branch_ids
    start, _ = periods.bounds(day, day)
    yday = day - timedelta(days=1)
    y_start, _ = periods.bounds(yday, yday)
    collected, methods = money_for(ids, start, now)
    # Yesterday up to the same time, so mid-morning isn't compared with a full day.
    prev, _ = money_for(ids, y_start, y_start + (now - start))
    note = _change(collected, prev, 'this time yesterday')
    j = jobs_for(ids, start, now)
    n_cuts, off, _ = discounts_for(start, now)
    up, total = _machines(ids)
    due = due_on(ids, day)
    alerts = needs_you(day)
    local = timezone.localtime(now)

    rows = [('Machines up', f'{up} of {total}'), ('Still due today', due)]
    if n_cuts:
        rows.append((f'Discounts · {n_cuts}', amount(off)))
    text = compose(
        f'📊 *Today so far · {local:%H:%M}*',
        f'_{_short_day(day)}_',
        RULE,
        hero('Collected so far', ghs(collected), note),
        _jobs_table(j),
        RULE,
        methods and '💳 *How it was paid* · GHS',
        methods and _method_table(methods),
        '⚙️ *Right now*',
        table(rows),
        RULE,
        needs_you_text(alerts),
    )

    sections = []
    if methods:
        sections.append({'title': 'How it was paid', 'rows': _method_rows(methods)})
    sections.append({'title': 'Right now', 'rows': [(a, f'GHS {b}' if a.startswith('Discounts') else str(b))
                                                    for a, b in rows]})
    sections.append(_alert_section(alerts))
    card = {
        'kicker': 'Today so far', 'date': f'{_day_name(day)} · {local:%H:%M}',
        'greeting': '',
        'hero': {'label': 'Collected so far', 'value': ghs(collected), 'note': note},
        'tiles': [('Jobs taken', str(j['taken'])), ('Finished', str(j['finished'])), ('Promises kept', _kept(j))],
        'sections': sections,
        'footer': f'As at {local:%H:%M}',
    }
    caption = f'So far today: {ghs(collected)} collected. {_alert_words(alerts)}'
    return {'text': text, 'card': card, 'caption': caption, 'knock': f'Today so far: {ghs(collected)} collected.'}
