"""
What Octos can look up for the owner (19 Nov 2026).

The owner's line talks to Khofi as his right hand: "who's on the till at
Westland?", "any queue at payment?", "what did she say?". Every answer
comes from one of these look-ups, and none of them changes anything: they
read the floor and report. The few that send something send it only to
the owner's own line (a report, a discount card with its buttons).

These tools are for the owner's line only. The customer assistant has its
own tools (tools.py) and never sees these: nothing here may reach a
customer chat.

Two rules keep the figure checker (checker.py) honest:
  money is always written as "GHS 1,234.00", never as a bare number
  clock times are always written like "8:04am", never as ISO strings
so every figure Octos repeats can be found, as written, in what it looked up.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

ZERO = Decimal('0')
DEAD = ('DRAFT', 'CANCELLED', 'VOIDED')
LIST_LIMIT = 15


# ── Writing figures the checker can find ───────────────────────────────────

def ghs(value):
    return f'GHS {Decimal(value or 0):,.2f}'


def clock(dt):
    """'8:04am', in Accra time."""
    if not dt:
        return None
    t = timezone.localtime(dt)
    return f'{t.hour % 12 or 12}:{t.minute:02d}{"am" if t.hour < 12 else "pm"}'


def when(dt, now=None):
    """'8:04am' today, 'yesterday 4:10pm', or 'Mon 16 Nov 4:10pm'."""
    if not dt:
        return None
    now = now or timezone.now()
    day, today = timezone.localtime(dt).date(), timezone.localtime(now).date()
    if day == today:
        return clock(dt)
    if day == today - timedelta(days=1):
        return f'yesterday {clock(dt)}'
    t = timezone.localtime(dt)
    return f'{t:%a} {t.day} {t:%b} {clock(dt)}'


def minutes_since(dt, now=None):
    if not dt:
        return None
    return max(int(((now or timezone.now()) - dt).total_seconds() // 60), 0)


def waited(dt, now=None):
    """'12 min', '2 h 5 min', '3 days'."""
    m = minutes_since(dt, now)
    if m is None:
        return None
    if m < 60:
        return f'{m} min'
    if m < 24 * 60:
        h, r = divmod(m, 60)
        return f'{h} h {r} min' if r else f'{h} h'
    d = m // (24 * 60)
    return f'{d} day{"s" if d > 1 else ""}'


# ── Branches ───────────────────────────────────────────────────────────────

def branches(wanted=''):
    """
    The branches matching the name ("westland", "Madina"), or, with no name,
    the trading ones: a branch not yet trading has nothing to report and
    only clutters the answer ("the other five branches have no tills open",
    19 Nov 2026). Named, any active branch can be looked at.
    Returns (branches, error): error is set when a name matches nothing.
    """
    from apps.organization.models import Branch
    every = list(Branch.objects.filter(is_active=True).order_by('name'))
    wanted = (wanted or '').strip().lower().replace(' branch', '')
    if not wanted or wanted in ('all', 'every', 'everywhere', 'company', 'all branches'):
        trading = [b for b in every if b.is_trading]
        return trading or every, None
    exact = [b for b in every if short(b).lower() == wanted]
    found = exact or [b for b in every if wanted in (b.name or '').lower()]
    if not found:
        names = ', '.join(short(b) for b in every)
        return [], {'error': f'No branch called "{wanted}". The branches are: {names}.'}
    return found, None


def short(branch):
    return (branch.name or '').replace(' Branch', '')


def _ids(found):
    return [b.pk for b in found]


# ── Who is on duty ─────────────────────────────────────────────────────────

def _today_sheet(branch, day):
    from apps.finance.models import DailySalesSheet
    return DailySalesSheet.objects.filter(branch=branch, date=day).first()


def _tills(sheet):
    """The cashiers on the sheet today: who, since when, signed off or not."""
    from apps.analytics.models import UserSession
    from apps.finance.models import CashierFloat
    if sheet is None:
        return []
    rows = []
    floats = (CashierFloat.objects.filter(daily_sheet=sheet)
              .select_related('cashier').order_by('shift_sequence', 'pk'))
    for f in floats:
        if not f.cashier_id:
            continue
        first_session = (UserSession.objects.filter(user_id=f.cashier_id, started_at__date=sheet.date)
                         .order_by('started_at').values_list('started_at', flat=True).first())
        since = f.morning_acknowledged_at or first_session or f.float_set_at
        rows.append({
            'cashier': f.cashier.full_name,
            'on_till': not f.is_signed_off,
            'took_float_at': clock(f.morning_acknowledged_at),
            'signed_into_octos_at': clock(first_session),
            'since': clock(since),
            'signed_off_at': clock(f.signed_off_at) if f.is_signed_off else None,
            'covering': bool(f.is_cover),
        })
    return rows


def who_is_in(branch=''):
    """Everyone's attendance today, branch by branch."""
    from apps.eye.services import people
    found, error = branches(branch)
    if error:
        return error
    day = timezone.localdate()
    users = list(people.staff(_ids(found)))
    ledger = people.Ledger(users, day, day)
    out = []
    for b in found:
        rows = []
        for u in users:
            if u.branch_id != b.pk:
                continue
            st, clocked, start_t = ledger.status(u, day)
            rows.append({
                'name': u.full_name, 'role': people.role_label(u.role),
                'status': people.LABEL[st],
                'clocked_in': clock(clocked),
                'signed_into_octos': clock(ledger.session[u.pk].get(day)),
                'shift_starts': _time_words(start_t),
            })
        out.append({'branch': short(b), 'tills': _tills(_today_sheet(b, day)), 'people': rows})
    return out


def _time_words(t):
    if t is None:
        return None
    return f'{t.hour % 12 or 12}:{t.minute:02d}{"am" if t.hour < 12 else "pm"}'


# ── The floor right now ────────────────────────────────────────────────────

def _payment_queue(ids):
    from apps.jobs.models import Job
    return (Job.objects.filter(branch_id__in=ids, status=Job.PENDING_PAYMENT)
            .select_related('customer', 'branch', 'intake_by').order_by('created_at'))


def _in_production(ids):
    from apps.eye.services import jobs
    return jobs.live_line(ids).exclude(work_state='DONE')


def _ready(ids):
    from apps.jobs.models import Job
    return (Job.objects.filter(branch_id__in=ids, work_state='DONE')
            .exclude(status__in=DEAD).exclude(handover_state='HANDED_OVER')
            .exclude(job_type='INSTANT'))


def _overdue(ids, now):
    from apps.jobs.models import Job
    return (Job.objects.filter(branch_id__in=ids, estimated_ready_at__lt=now)
            .exclude(status__in=DEAD).exclude(work_state='DONE')
            .exclude(handover_state='HANDED_OVER').exclude(job_type='INSTANT'))


def branch_pulse(branch=''):
    """How each branch is doing right now: day, till, queue, line, money."""
    from apps.eye.services import jobs as eye_jobs, money, periods
    found, error = branches(branch)
    if error:
        return error
    now = timezone.now()
    day = timezone.localdate()
    start, end = periods.bounds(day, day)
    out = []
    for b in found:
        ids = [b.pk]
        sheet = _today_sheet(b, day)
        queue = list(_payment_queue(ids))
        oldest = queue[0] if queue else None
        out.append({
            'branch': short(b),
            'day': ('open' if sheet and sheet.status == 'OPEN' else
                    'closed' if sheet else 'not opened today'),
            'day_opened_at': clock(sheet.opened_at) if sheet else None,
            'day_closed_at': clock(sheet.closed_at) if sheet and sheet.closed_at else None,
            'tills': _tills(sheet),
            'waiting_to_pay': len(queue),
            'longest_wait_to_pay': waited(oldest.created_at, now) if oldest else None,
            'in_production': _in_production(ids).count(),
            'ready_for_collection': _ready(ids).count(),
            'past_promise': _overdue(ids, now).count(),
            'jobs_taken_today': eye_jobs.taken(ids, start, end).count(),
            'collected_today': ghs(money.collected(ids, start, end)),
        })
    return out


def _job_row(job, now):
    row = {
        'job': job.job_number,
        'what': job.title,
        'customer': job.customer.full_name if job.customer_id else 'walk-in',
        'branch': short(job.branch) if job.branch_id else '',
        'price': ghs(job.estimated_cost),
    }
    if job.amount_paid:
        row['paid'] = ghs(job.amount_paid)
    if job.balance_due:
        row['balance'] = ghs(job.balance_due)
    return row


def payment_queue(branch=''):
    """Jobs waiting at the cashier to be paid for, oldest first."""
    found, error = branches(branch)
    if error:
        return error
    now = timezone.now()
    queue = list(_payment_queue(_ids(found))[:LIST_LIMIT + 1])
    rows = []
    for job in queue[:LIST_LIMIT]:
        row = _job_row(job, now)
        row['waiting'] = waited(job.created_at, now)
        row['sent_to_cashier_at'] = when(job.created_at, now)
        if job.intake_by_id:
            row['taken_by'] = job.intake_by.full_name
        if job.carried_forward:
            row['carried_from_earlier_day'] = True
        rows.append(row)
    total = sum((j.estimated_cost or ZERO) for j in _payment_queue(_ids(found)))
    return {'branches': [short(b) for b in found], 'waiting': _payment_queue(_ids(found)).count(),
            'total_waiting_to_be_paid': ghs(total), 'jobs': rows,
            'more_not_shown': len(queue) > LIST_LIMIT}


JOB_LISTS = ('taken_today', 'in_production', 'ready_for_collection', 'past_promise', 'at_risk', 'due_today')


def job_list(which, branch=''):
    """A list of live jobs: in production, ready, past promise, at risk, due today."""
    from apps.eye.services import periods
    from apps.jobs.models import Job
    if which not in JOB_LISTS:
        return {'error': f'Ask for one of: {", ".join(JOB_LISTS)}.'}
    found, error = branches(branch)
    if error:
        return error
    ids, now = _ids(found), timezone.now()
    if which == 'taken_today':
        start, end = periods.bounds(timezone.localdate(), timezone.localdate())
        qs = (Job.objects.filter(branch_id__in=ids, created_at__gte=start, created_at__lt=end)
              .exclude(status__in=DEAD))
    elif which == 'in_production':
        qs = _in_production(ids)
    elif which == 'ready_for_collection':
        qs = _ready(ids)
    elif which == 'past_promise':
        qs = _overdue(ids, now)
    elif which == 'at_risk':
        qs = (Job.objects.filter(branch_id__in=ids, promise_state='AT_RISK')
              .exclude(status__in=DEAD).exclude(work_state='DONE'))
    else:
        start, end = periods.bounds(timezone.localdate(), timezone.localdate())
        qs = (Job.objects.filter(branch_id__in=ids, estimated_ready_at__gte=start, estimated_ready_at__lt=end)
              .exclude(status__in=DEAD).exclude(handover_state='HANDED_OVER'))
    qs = qs.select_related('customer', 'branch')
    count = qs.count()
    rows = []
    order = ('-created_at',) if which == 'taken_today' else ('estimated_ready_at', 'created_at')
    for job in qs.select_related('intake_by').order_by(*order)[:LIST_LIMIT]:
        row = _job_row(job, now)
        if which == 'taken_today':
            row['taken_at'] = clock(job.created_at)
            row['taken_by'] = job.intake_by.full_name if job.intake_by_id else None
        row['stage'] = job.get_work_state_display() if job.work_state else job.get_status_display()
        if job.estimated_ready_at:
            row['promised'] = when(job.estimated_ready_at, now)
        if which == 'ready_for_collection' and job.updated_at:
            row['ready_for'] = waited(job.updated_at, now)
        rows.append(row)
    return {'list': which, 'branches': [short(b) for b in found], 'count': count, 'jobs': rows,
            'more_not_shown': count > LIST_LIMIT}


def find_job(query):
    """A job by its number, or a customer's recent jobs by name or phone."""
    from apps.jobs.models import Job
    query = (query or '').strip()
    if not query:
        return {'error': 'Give a job number or a customer name.'}
    now = timezone.now()
    digits = ''.join(ch for ch in query if ch.isdigit())
    qs = Job.objects.exclude(status='DRAFT').select_related('customer', 'branch', 'intake_by')
    if digits and len(digits) <= 6 and len(digits) >= 3:
        matches = list(qs.filter(job_number__endswith=digits).order_by('-created_at')[:3])
    else:
        who = Q(customer__first_name__icontains=query) | Q(customer__last_name__icontains=query)
        parts = query.split()
        if len(parts) >= 2:
            who |= Q(customer__first_name__icontains=parts[0], customer__last_name__icontains=parts[-1])
        if len(digits) >= 9:
            # However the number was stored (0244…, +233244…), its last nine digits match.
            who = Q(customer__phone__endswith=digits[-9:]) | Q(customer__secondary_phone__endswith=digits[-9:])
        matches = list(qs.filter(who).order_by('-created_at')[:5])
    if not matches:
        return {'found': 0, 'say': f'Nothing matches "{query}".'}
    rows = []
    for job in matches:
        row = _job_row(job, now)
        row.update({
            'status': job.get_status_display(),
            'stage': job.get_work_state_display() if job.work_state else None,
            'handed_over': job.handover_state == 'HANDED_OVER',
            'taken_at': when(job.created_at, now),
            'taken_by': job.intake_by.full_name if job.intake_by_id else None,
        })
        if job.estimated_ready_at:
            row['promised'] = when(job.estimated_ready_at, now)
        if job.promise_state in ('AT_RISK', 'LATE', 'BROKEN'):
            row['promise'] = job.promise_state.replace('_', ' ').lower()
        if job.discount_amount:
            row['discount'] = f'{ghs(job.discount_amount)} off · {job.discount_reason}'
        rows.append(row)
    return {'found': len(rows), 'jobs': rows}


# ── Money ──────────────────────────────────────────────────────────────────

PERIODS = ('today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month')


def _period(name, today):
    if name == 'today':
        return today, today, 'today'
    if name == 'yesterday':
        d = today - timedelta(days=1)
        return d, d, 'yesterday'
    if name == 'this_week':
        return today - timedelta(days=today.weekday()), today, 'this week so far'
    if name == 'last_week':
        first = today - timedelta(days=today.weekday() + 7)
        return first, first + timedelta(days=6), 'last week'
    if name == 'this_month':
        return today.replace(day=1), today, 'this month so far'
    last = today.replace(day=1) - timedelta(days=1)
    return last.replace(day=1), last, 'last month'


def money_report(period='today', branch=''):
    """Money in, by method and by branch; jobs taken and finished; discounts; what's owed."""
    from apps.communications.services import owner_reports
    from apps.eye.services import money, periods
    if period not in PERIODS:
        return {'error': f'Ask for one of: {", ".join(PERIODS)}.'}
    found, error = branches(branch)
    if error:
        return error
    ids = _ids(found)
    first, last, label = _period(period, timezone.localdate())
    start, end = periods.bounds(first, last)
    collected, methods = owner_reports.money_for(ids, start, end)
    jobs = owner_reports.jobs_for(ids, start, end)
    out = {
        'period': label,
        'from': f'{first:%a} {first.day} {first:%b}', 'to': f'{last:%a} {last.day} {last:%b}',
        'branches': [short(b) for b in found],
        'collected': ghs(collected),
        'by_method': [{'method': m, 'payments': n, 'amount': ghs(a)} for m, n, a in methods],
        'jobs_taken': jobs['taken'], 'jobs_finished': jobs['finished'],
        'promises_kept': f"{jobs['kept_pct']}%" if jobs['kept_pct'] is not None else None,
    }
    if len(found) > 1:
        out['by_branch'] = [{'branch': short(b), 'collected': ghs(money.collected([b.pk], start, end))}
                            for b in found]
    count, off, rows = owner_reports.discounts_for(start, end)
    if count:
        out['discounts'] = {'count': count, 'total_off': ghs(off),
                            'items': [{'on': w, 'off': ghs(a), 'reason': r} for w, a, r in rows[:5]]}
    same = _same_span(period, start, end)
    if same:
        before_start, before_end, words = same
        before = money.collected(ids, before_start, before_end)
        before_jobs = owner_reports.jobs_for(ids, before_start, before_end)['taken']
        out['compared_with'] = {
            'span': words,
            'collected': ghs(before), 'jobs_taken': before_jobs,
            'money_change': _pct(collected, before), 'jobs_change': _pct(jobs['taken'], before_jobs),
        }
    owed = money.owed(ids)
    out['owed_to_us_now'] = {'job_balances': ghs(owed['job_balances']),
                             'credit_accounts': ghs(owed['credit_owed']),
                             'total': ghs(owed['job_balances'] + owed['credit_owed'])}
    return out


def _same_span(period, start, end):
    """
    The same stretch of time one period back, so a comparison is fair: this
    week so far (Monday to now) against last week's Monday to the same hour,
    not the whole of last week (19 Nov 2026). None for finished periods,
    which compare with the one before as they stand.
    """
    now = timezone.now()
    if period == 'today':
        shift, words = timedelta(days=7), 'the same day last week, up to this time'
    elif period == 'this_week':
        shift, words = timedelta(days=7), 'last week, from Monday up to this day and time'
    elif period == 'this_month':
        local = timezone.localtime(now)
        prev_last_day = (local.replace(day=1) - timedelta(days=1)).day
        day = min(local.day, prev_last_day)
        prev_start = start.replace(month=start.month - 1 if start.month > 1 else 12,
                                   year=start.year if start.month > 1 else start.year - 1)
        prev_now = timezone.localtime(now).replace(year=prev_start.year, month=prev_start.month, day=day)
        return prev_start, prev_now, 'last month, from the 1st up to this day and time'
    elif period in ('yesterday', 'last_week', 'last_month'):
        if period == 'yesterday':
            return start - timedelta(days=7), end - timedelta(days=7), 'the same day the week before'
        if period == 'last_week':
            return start - timedelta(days=7), start, 'the week before'
        prev_end = start
        prev_start = timezone.localtime(start - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0,
                                                                         microsecond=0)
        return prev_start, prev_end, 'the month before'
    else:
        return None
    return start - shift, min(end, now) - shift, words


def _pct(now_value, before_value):
    """'+56%', '-8%', or None when there is nothing to compare with."""
    from apps.eye.services import periods
    change = periods.change(now_value, before_value)
    if change is None:
        return None
    return f'{"+" if change > 0 else ""}{change}%'


def who_owes(branch=''):
    """
    Who owes us right now: customers with a balance left on a job (deposit
    paid, rest due) and credit accounts carrying a balance, biggest first.
    The totals match owed_to_us_now in money_report.
    """
    from apps.eye.services import money
    from apps.finance.models import CreditAccount
    from apps.jobs.models import Job
    found, error = branches(branch)
    if error:
        return error
    ids, now = _ids(found), timezone.now()
    live = (Job.objects.filter(branch_id__in=ids, payment_state='DEPOSIT_PAID')
            .exclude(status__in=['CANCELLED', 'VOIDED']).select_related('customer', 'branch'))
    people = {}
    for job in live:
        due = job.balance_due or ZERO
        if due <= 0:
            continue
        who = job.customer.full_name if job.customer_id else f'walk-in on {job.job_number}'
        row = people.setdefault(who, {'customer': who, 'owes': ZERO, 'jobs': []})
        row['owes'] += due
        row['jobs'].append({'job': job.job_number, 'what': job.title, 'balance': ghs(due),
                            'stage': job.get_work_state_display() if job.work_state else job.get_status_display(),
                            'taken': when(job.created_at, now)})
    rows = sorted(people.values(), key=lambda r: -r['owes'])
    for r in rows:
        r['owes'] = ghs(r['owes'])
        r['jobs'] = r['jobs'][:3]
    accounts = (CreditAccount.objects.filter(branch_id__in=ids, status='ACTIVE', current_balance__gt=0)
                .select_related('customer').order_by('-current_balance'))
    owed = money.owed(ids)
    return {
        'total_owed': ghs(owed['job_balances'] + owed['credit_owed']),
        'job_balances': {'total': ghs(owed['job_balances']), 'customers': len(rows), 'biggest_first': rows[:10]},
        'credit_accounts': {'total': ghs(owed['credit_owed']),
                            'accounts': [{'customer': a.customer.full_name if a.customer_id else '',
                                          'owes': ghs(a.current_balance), 'limit': ghs(a.credit_limit),
                                          'over_limit': a.is_over_limit} for a in accounts[:10]]},
    }


# ── WhatsApp ───────────────────────────────────────────────────────────────

def _handler(conversation):
    from apps.communications.models import Conversation
    if conversation.handled_by == Conversation.STAFF:
        who = conversation.assigned_to.full_name if conversation.assigned_to_id else 'a person'
        return f'{who} (took it {when(conversation.handled_since)})' if conversation.handled_since else who
    if conversation.handoff_reason:
        return f'Octos, asking for a person: {conversation.handoff_reason}'
    return 'Octos'


def _said(message):
    """One message, in words: the text, or what the file was."""
    words = (message.body or '').strip()
    if message.message_type in ('IMAGE', 'VIDEO', 'DOCUMENT', 'AUDIO'):
        what = message.media_name or message.get_message_type_display().lower()
        if message.media_pages:
            what += f', {message.media_pages} pages'
        words = f'[file: {what}]' + (f' {words}' if words else '')
    return words[:400]


def whatsapp_chats(view='waiting'):
    """
    WhatsApp chats: 'waiting' (a customer's last message is unanswered),
    'with_staff' (a person has taken the chat) or 'recent' (the latest chats).
    """
    from apps.communications.models import Conversation
    from apps.communications.services.handover import waiting_since
    now = timezone.now()
    live = (Conversation.objects.filter(channel=Conversation.WHATSAPP)
            .exclude(status__in=[Conversation.RESOLVED, Conversation.SPAM])
            .select_related('customer', 'assigned_to', 'branch'))
    if view == 'with_staff':
        qs = live.filter(handled_by=Conversation.STAFF).order_by('-last_message_at')[:LIST_LIMIT]
    elif view == 'recent':
        qs = live.filter(last_message_at__gte=now - timedelta(hours=24)).order_by('-last_message_at')[:LIST_LIMIT]
    else:
        view = 'waiting'
        qs = live.filter(last_message_at__gte=now - timedelta(days=2)).order_by('-last_message_at')[:60]
    rows = []
    for c in qs:
        since = waiting_since(c)
        if view == 'waiting' and since is None:
            continue
        last = (c.messages.filter(is_internal_note=False).exclude(kind__in=('reaction', 'unsupported'))
                .order_by('-created_at').first())
        rows.append({
            'chat_id': c.pk, 'customer': c.display_name,
            'branch': short(c.branch) if c.branch_id else None,
            'handled_by': _handler(c),
            'customer_waiting': waited(since, now) if since else None,
            'last_message': _said(last) if last else None,
            'last_message_from': ('customer' if last and last.direction == 'INBOUND' else 'Farhat') if last else None,
            'last_message_at': when(last.created_at, now) if last else None,
        })
        if len(rows) >= LIST_LIMIT:
            break
    return {'view': view, 'chats': rows, 'count': len(rows)}


def read_chat(chat_id=None, customer=''):
    """The latest messages of one WhatsApp chat, by its chat_id or the customer's name."""
    from apps.communications.models import Conversation
    now = timezone.now()
    c = None
    if chat_id:
        c = Conversation.objects.filter(pk=chat_id).select_related('customer', 'assigned_to').first()
    elif customer:
        name = customer.strip()
        c = (Conversation.objects.filter(
                Q(contact_name__icontains=name) | Q(customer__first_name__icontains=name)
                | Q(customer__last_name__icontains=name) | Q(contact_username__icontains=name))
             .select_related('customer', 'assigned_to').order_by('-last_message_at').first())
    if c is None:
        return {'error': 'No chat found. Look at whatsapp_chats for the chat_id.'}
    messages = list(c.messages.filter(is_internal_note=False)
                    .exclude(kind__in=('reaction', 'unsupported'))
                    .select_related('sent_by').order_by('-created_at')[:12])
    lines = []
    for m in reversed(messages):
        if m.direction == 'INBOUND':
            who = 'customer'
        elif m.sent_by_id:
            who = m.sent_by.full_name
        else:
            who = 'Octos'
        lines.append({'at': when(m.created_at, now), 'from': who, 'said': _said(m)})
    return {'chat_id': c.pk, 'customer': c.display_name, 'handled_by': _handler(c), 'messages': lines}


# ── Machines ───────────────────────────────────────────────────────────────

def machines(branch=''):
    from apps.production.models import Machine
    found, error = branches(branch)
    if error:
        return error
    rows = []
    for m in Machine.objects.filter(branch_id__in=_ids(found), is_active=True).select_related('branch'):
        row = {'machine': m.name, 'branch': short(m.branch) if m.branch_id else '',
               'working': bool(m.is_available)}
        if not m.is_available:
            row['down_since'] = when(m.unavailable_since)
            row['reason'] = m.unavailable_reason or 'No reason given'
        rows.append(row)
    return {'machines': rows, 'down': sum(1 for r in rows if not r['working'])}


# ── One person's work ──────────────────────────────────────────────────────

def _staff_named(name):
    """Active staff (not the owner) whose name matches: [users]."""
    from apps.accounts.models import CustomUser
    name = (name or '').strip()
    qs = CustomUser.objects.filter(is_active=True, is_business_owner=False).select_related('branch', 'role')
    parts = name.split()
    if len(parts) >= 2:
        both = qs.filter(first_name__icontains=parts[0], last_name__icontains=parts[-1])
        if both.exists():
            return list(both)
    return list(qs.filter(Q(first_name__icontains=name) | Q(last_name__icontains=name))[:6])


def staff_activity(person, period='today'):
    """
    What one member of staff did in a period: jobs they took at the counter
    (what the floor often calls issuing an invoice), formal invoices and
    proformas they issued, payments they received, WhatsApp replies they
    sent, discounts they asked for; and, for today, when they came in.
    Asked on 19 Nov 2026: "Has he issued any invoice today?"
    """
    from apps.communications.models import Message
    from apps.eye.services import people, periods
    from apps.finance.models import Invoice, Receipt
    from apps.jobs.models import Job, PriceCut, ProformaInvoice
    if period not in PERIODS:
        return {'error': f'Ask for one of: {", ".join(PERIODS)}.'}
    found = _staff_named(person)
    if not found:
        return {'error': f'No member of staff called "{person}".'}
    if len(found) > 1:
        return {'more_than_one': [{'name': u.full_name, 'role': people.role_label(u.role),
                                   'branch': short(u.branch) if u.branch_id else ''} for u in found],
                'say': 'Ask him which one he means.'}
    user = found[0]
    now = timezone.now()
    first, last, label = _period(period, timezone.localdate())
    start, end = periods.bounds(first, last)
    out = {'name': user.full_name, 'role': people.role_label(user.role),
           'branch': short(user.branch) if user.branch_id else '', 'period': label}

    if period == 'today':
        ledger = people.Ledger([user], first, last)
        st, clocked, start_t = ledger.status(user, first)
        out['today'] = {'status': people.LABEL[st], 'clocked_in': clocked and clock(clocked),
                        'signed_into_octos': clock(ledger.session[user.pk].get(first)),
                        'shift_starts': _time_words(start_t)}

    jobs = (Job.objects.filter(intake_by=user, created_at__gte=start, created_at__lt=end)
            .exclude(status__in=DEAD).select_related('customer', 'branch').order_by('-created_at'))
    job_total = sum((j.estimated_cost or ZERO) for j in jobs)
    out['jobs_taken'] = {
        'count': jobs.count(), 'total_value': ghs(job_total),
        'latest': [{'job': j.job_number, 'what': j.title,
                    'customer': j.customer.full_name if j.customer_id else 'walk-in',
                    'price': ghs(j.estimated_cost), 'status': j.get_status_display(),
                    'at': when(j.created_at, now)} for j in jobs[:8]],
    }

    invoices = Invoice.objects.filter(generated_by=user, created_at__gte=start, created_at__lt=end)
    out['formal_invoices'] = {
        'count': invoices.count(), 'total': ghs(sum((i.total or ZERO) for i in invoices)),
        'latest': [{'number': i.invoice_number, 'type': i.get_invoice_type_display(), 'to': i.bill_to_name,
                    'total': ghs(i.total), 'status': i.get_status_display()} for i in invoices.order_by('-created_at')[:5]],
    }

    proformas = (ProformaInvoice.objects.filter(issued_by=user)
                 .filter(Q(issued_at__gte=start, issued_at__lt=end)
                         | Q(issued_at__isnull=True, created_at__gte=start, created_at__lt=end)))
    out['proformas'] = {
        'count': proformas.count(), 'total': ghs(sum((p.total or ZERO) for p in proformas)),
        'latest': [{'number': p.proforma_number, 'to': p.issued_to, 'total': ghs(p.total),
                    'status': p.get_status_display()} for p in proformas.order_by('-created_at')[:5]],
    }

    receipts = Receipt.objects.filter(cashier=user, is_void=False, created_at__gte=start, created_at__lt=end)
    if receipts.exists():
        out['payments_received'] = {'count': receipts.count(),
                                    'total': ghs(sum((r.amount_paid or ZERO) for r in receipts))}

    replies = Message.objects.filter(sent_by=user, direction=Message.OUTBOUND, is_internal_note=False,
                                     created_at__gte=start, created_at__lt=end)
    if replies.exists():
        out['whatsapp_replies'] = {'messages': replies.count(),
                                   'chats': replies.values('conversation_id').distinct().count()}

    cuts = PriceCut.objects.filter(asked_by=user, created_at__gte=start, created_at__lt=end)
    if cuts.exists():
        out['discounts_asked'] = {'count': cuts.count(),
                                  'still_waiting_for_you': cuts.filter(status=PriceCut.Status.PENDING).count()}
    return out
