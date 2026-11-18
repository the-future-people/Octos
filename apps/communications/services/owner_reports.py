"""
What the owner's line reports (18 Nov 2026): the morning brief, the day's
close and "today so far". Each one gives:

  card   plain data for the picture (owner_cards.render)
  text   the words that go under the picture: short, readable at a glance
  knock  one line for the template when WhatsApp's window is shut

Every figure comes from the Eye's own services (apps/eye/services), so the
owner's phone and the Eye can never disagree.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

ZERO = Decimal('0')
DEAD = ('DRAFT', 'CANCELLED', 'VOIDED')


def ghs(amount):
    return f'GHS {Decimal(amount or 0):,.2f}'


def _day_name(day):
    return f'{day:%A} {day.day} {day:%B}'


def _short_day(day):
    return f'{day:%a} {day.day} {day:%b}'


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
    from apps.eye.services import money
    from apps.finance.payment_methods import BY_CODE
    collected = money.collected(ids, start, end)
    methods = []
    for code, row in sorted(money.by_method(ids, start, end).items(), key=lambda kv: -kv[1]['amount']):
        label = BY_CODE[code].label if code in BY_CODE else (code or 'Other').title()
        methods.append((f"{label} · {row['count']}", ghs(row['amount'])))
    return collected, methods


def jobs_for(ids, start, end):
    from apps.eye.services import jobs
    kept_pct, kept, broken = jobs.promise_kept(ids, start, end)
    return {
        'taken': jobs.taken(ids, start, end).count(),
        'finished': jobs.finished(ids, start, end),
        'kept_pct': kept_pct, 'kept': kept, 'broken': broken,
    }


def discounts_for(start, end):
    """Price cuts that took effect in the window: (count, total off, lines)."""
    from apps.jobs.models import PriceCut
    cuts = (PriceCut.objects.filter(status=PriceCut.Status.APPLIED)
            .filter(Q(decided_at__gte=start, decided_at__lt=end)
                    | Q(decided_at__isnull=True, created_at__gte=start, created_at__lt=end))
            .select_related('job', 'proforma', 'asked_by').order_by('created_at'))
    total, lines = ZERO, []
    for c in cuts:
        total += c.amount or ZERO
        what = c.job.job_number if c.job_id else c.proforma.proforma_number
        lines.append(f'{what}: {ghs(c.amount)} off · {c.reason}')
    return len(lines), total, lines


def cash_for(ids, day):
    """Each cashier's sign-off for the day: lines, and the total short."""
    from apps.finance.models import CashierFloat
    floats = (CashierFloat.objects.filter(daily_sheet__branch_id__in=ids, daily_sheet__date=day,
                                          is_signed_off=True)
              .select_related('cashier'))
    lines, short = [], ZERO
    for f in floats:
        v = f.variance or ZERO
        if abs(v) < Decimal('0.01'):
            lines.append((f'{f.cashier.full_name}', 'Balanced'))
        elif v < 0:
            short += -v
            lines.append((f'{f.cashier.full_name}', f'Short {ghs(-v)}'))
        else:
            lines.append((f'{f.cashier.full_name}', f'Over {ghs(v)}'))
    return lines, short


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


def branch_lines(sc, start, end):
    """Money per branch, only when there is more than one branch with money."""
    from apps.eye.services import money
    from apps.organization.models import Branch
    rows = []
    for b in Branch.objects.filter(pk__in=sc.branch_ids).order_by('name'):
        amount = money.collected((b.pk,), start, end)
        if amount:
            rows.append((b.name.replace(' Branch', ''), ghs(amount)))
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

def brief(day=None):
    """Before opening: yesterday in numbers, and what today holds."""
    from apps.eye.services import periods
    day = day or timezone.localdate()
    yday, before = day - timedelta(days=1), day - timedelta(days=2)
    sc = _company()
    ids = sc.branch_ids
    start, end = periods.bounds(yday, yday)
    p_start, p_end = periods.bounds(before, before)
    collected, methods = money_for(ids, start, end)
    prev, _ = money_for(ids, p_start, p_end)
    j = jobs_for(ids, start, end)
    n_cuts, off, _ = discounts_for(start, end)
    due = due_on(ids, day)
    up, total = _machines(ids)
    owed = _owed(ids)
    alerts = needs_you(day)

    sections = []
    if methods:
        sections.append({'title': 'How it was paid', 'rows': methods})
    lines = branch_lines(sc, start, end)
    if lines:
        sections.append({'title': 'By branch', 'rows': lines})
    today_rows = [('Jobs due today', str(due)), ('Machines up', f'{up} of {total}')]
    if owed:
        today_rows.append(('Still owed to us', ghs(owed)))
    if n_cuts:
        today_rows.append((f'Discounts yesterday · {n_cuts}', ghs(off)))
    sections.append({'title': 'Today', 'rows': today_rows})
    sections.append(_alert_section(alerts))

    name = _owner_name()
    card = {
        'kicker': 'Morning brief', 'date': _day_name(day),
        'greeting': f'Good morning, {name}',
        'hero': {'label': f'Collected yesterday, {_short_day(yday)}', 'value': ghs(collected),
                 'note': _change(collected, prev, f'{before:%A}')},
        'tiles': [('Jobs taken', str(j['taken'])), ('Finished', str(j['finished'])),
                  ('Promises kept', f"{j['kept_pct']}%" if j['kept_pct'] is not None else '–')],
        'sections': sections,
        'footer': 'Reply "today" any time for the latest',
    }
    text = (f'☀️ Good morning, {name}.\n'
            f'Yesterday: {ghs(collected)} collected, {j["taken"]} jobs taken, {j["finished"]} finished.\n'
            f'Today: {due} job{"s" if due != 1 else ""} due, {up} of {total} machines up.\n'
            f'{_alert_words(alerts)}')
    knock = (f'Your morning brief for {_short_day(day)} is ready. Yesterday {ghs(collected)} collected, '
             f'{due} jobs due today.')
    return {'card': card, 'text': text, 'knock': knock}


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
    j = jobs_for(ids, start, end)
    n_cuts, off, cut_lines = discounts_for(start, end)
    cash, short = cash_for(ids, day)
    alerts = needs_you(day)

    sections = []
    if methods:
        sections.append({'title': 'How it was paid', 'rows': methods})
    lines = branch_lines(sc, start, end)
    if lines:
        sections.append({'title': 'By branch', 'rows': lines})
    if cash:
        sections.append({'title': 'Cash at sign-off', 'rows': cash})
    if n_cuts:
        sections.append({'title': f'Discounts · {n_cuts} · {ghs(off)} off',
                         'items': [('amber', line) for line in cut_lines[:5]]})
    sections.append(_alert_section(alerts))

    card = {
        'kicker': 'Day close', 'date': _day_name(day),
        'greeting': 'Here is how today went',
        'hero': {'label': 'Collected today', 'value': ghs(collected),
                 'note': _change(collected, prev, 'yesterday')},
        'tiles': [('Jobs taken', str(j['taken'])), ('Finished', str(j['finished'])),
                  ('Promises kept', f"{j['kept_pct']}%" if j['kept_pct'] is not None else '–')],
        'sections': sections,
        'footer': 'Good night from Octos',
    }
    cash_words = f' Cash short {ghs(short)}.' if short else ''
    disc_words = f' {n_cuts} discount{"s" if n_cuts != 1 else ""} ({ghs(off)} off).' if n_cuts else ''
    text = (f'🌙 Today: {ghs(collected)} collected, {j["taken"]} jobs taken, {j["finished"]} finished.'
            f'{cash_words}{disc_words}\n{_alert_words(alerts)}')
    knock = f'Your day close for {_short_day(day)} is ready. {ghs(collected)} collected today.'
    return {'card': card, 'text': text, 'knock': knock}


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
    j = jobs_for(ids, start, now)
    n_cuts, off, _ = discounts_for(start, now)
    up, total = _machines(ids)
    alerts = needs_you(day)
    local = timezone.localtime(now)

    sections = []
    if methods:
        sections.append({'title': 'How it was paid', 'rows': methods})
    rows = [('Machines up', f'{up} of {total}'), ('Still due today', str(due_on(ids, day)))]
    if n_cuts:
        rows.append((f'Discounts · {n_cuts}', ghs(off)))
    sections.append({'title': 'Right now', 'rows': rows})
    sections.append(_alert_section(alerts))
    card = {
        'kicker': 'Today so far', 'date': f'{_day_name(day)} · {local:%H:%M}',
        'greeting': '',
        'hero': {'label': 'Collected so far', 'value': ghs(collected),
                 'note': _change(collected, prev, 'this time yesterday')},
        'tiles': [('Jobs taken', str(j['taken'])), ('Finished', str(j['finished'])),
                  ('Promises kept', f"{j['kept_pct']}%" if j['kept_pct'] is not None else '–')],
        'sections': sections,
        'footer': f'As at {local:%H:%M}',
    }
    text = (f'So far today: {ghs(collected)} collected, {j["taken"]} jobs taken, {j["finished"]} finished.\n'
            f'{_alert_words(alerts)}')
    return {'card': card, 'text': text, 'knock': f'Today so far: {ghs(collected)} collected.'}
