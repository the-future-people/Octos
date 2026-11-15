"""
Who is on shift at a branch (15 Nov 2026), for the Branch Manager's sidebar.

On shift means signed in today. Every portal reports in through the
analytics session heartbeat (apps/analytics), but only while a person is
using it: a minute with no touch, key or click sends nothing. So a
session's last_seen_at is when someone last used Octos, not when a screen
was last left open, and "active" is the session engine's own 5-minute
idle rule.

Each person is in one of three states:
  active   used Octos in the last 5 minutes
  idle     signed in today, quiet for longer
  off      signed off today (attendant sign-off, cashier float), or signed out

Off wins: someone who has signed off is off, even if the locked portal
is still open in front of them.
"""
from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.analytics.engines.session_engine import IDLE_THRESHOLD_MIN

ACTIVE = 'active'
IDLE = 'idle'
OFF = 'off'

ACTIVE_WITHIN = timedelta(minutes=IDLE_THRESHOLD_MIN)
# Idle for longer than this reads as "Seen 3:40pm", not "Idle 214m".
IDLE_IN_MINUTES_UNTIL = timedelta(hours=1)
ORDER = {ACTIVE: 0, IDLE: 1, OFF: 2}

# Where someone works, by role. Operators are named by their machines instead.
PLACES = {
    'ATTENDANT': 'Front desk',
    'CASHIER': 'Till',
    'BRANCH_MANAGER': 'Manager',
    'FLOW_COORDINATOR': 'Production board',
    'COORDINATOR': 'Production board',
}


def on_shift(branch, now=None, viewer=None):
    """
    {'staff': [...], 'on': n, 'total': n} for the branch, today.

    Sorted active first, then idle, then off; within each, by name. The
    viewer is left out: the manager knows they are here.
    """
    from apps.analytics.models import UserSession

    now = now or timezone.now()
    day_start = timezone.make_aware(datetime.combine(timezone.localdate(now), time.min))

    sessions = (
        UserSession.objects
        .filter(user__branch=branch, user__is_active=True, last_seen_at__gte=day_start)
        .select_related('user', 'user__role')
        .order_by('user_id', '-last_seen_at')
    )
    if viewer is not None:
        sessions = sessions.exclude(user=viewer)

    latest = {}
    for session in sessions:
        latest.setdefault(session.user_id, session)   # newest first per user
    if not latest:
        return {'staff': [], 'on': 0, 'total': 0}

    signed_off = _signed_off(list(latest), day_start)
    machines = _machines(list(latest))

    staff = []
    for session in latest.values():
        user = session.user
        role = user.role.name if user.role_id else ''
        place = machines.get(user.pk) or PLACES.get(role) or (user.role.display_name if user.role_id else '')
        state, label = _state(session, signed_off.get(user.pk), place, now)
        staff.append({
            'id': user.pk,
            'name': user.first_name or user.full_name,
            'initial': (user.first_name or user.full_name or '?')[:1].upper(),
            'role': role,
            'place': place,
            'state': state,
            'label': label,
            'last_seen_at': session.last_seen_at.isoformat(),
        })

    staff.sort(key=lambda s: (ORDER[s['state']], s['name'].lower()))
    on = sum(1 for s in staff if s['state'] != OFF)
    return {'staff': staff, 'on': on, 'total': len(staff)}


def _state(session, off_at, place, now):
    if off_at is not None:
        return OFF, f'Off {_clock(off_at)}'
    if session.ended_at is not None:
        return OFF, f'Signed out {_clock(session.ended_at)}'
    quiet = now - session.last_seen_at
    if quiet <= ACTIVE_WITHIN:
        return ACTIVE, place
    if quiet < IDLE_IN_MINUTES_UNTIL:
        return IDLE, f'Idle {int(quiet.total_seconds() // 60)}m'
    return IDLE, f'Seen {_clock(session.last_seen_at)}'


def _signed_off(user_ids, day_start):
    """{user_id: when they signed off today}: attendant sign-offs and cashier floats."""
    from apps.finance.models import AttendantSignOff, CashierFloat

    off = {}
    for row in (AttendantSignOff.objects
                .filter(attendant_id__in=user_ids, signed_off_at__gte=day_start)
                .values('attendant_id', 'signed_off_at')):
        off[row['attendant_id']] = row['signed_off_at']

    # A cashier is off when their latest float today is signed off; a second
    # shift's open float means they're back on. Floats are often staged the
    # evening before, so "today" is the float's day, not when it was made.
    today = timezone.localdate(day_start)
    latest_float = {}
    for row in (CashierFloat.objects
                .filter(cashier_id__in=user_ids)
                .filter(Q(daily_sheet__date=today) | Q(scheduled_date=today))
                .order_by('cashier_id', '-shift_sequence', '-created_at')
                .values('cashier_id', 'is_signed_off', 'signed_off_at')):
        latest_float.setdefault(row['cashier_id'], row)
    for cashier_id, row in latest_float.items():
        if row['is_signed_off'] and row['signed_off_at']:
            off[cashier_id] = row['signed_off_at']
    return off


def _machines(user_ids):
    """{user_id: 'DTF · Heat press'}: the machines each operator runs now."""
    from apps.production.models import MachineOperator

    names = {}
    for row in (MachineOperator.objects
                .filter(operator_id__in=user_ids, active_until__isnull=True)
                .order_by('machine__name')
                .values('operator_id', 'machine__name')):
        names.setdefault(row['operator_id'], []).append(row['machine__name'])
    return {pk: ' · '.join(machines[:2]) + (f' +{len(machines) - 2}' if len(machines) > 2 else '')
            for pk, machines in names.items()}


def _clock(when):
    """8:12pm, in the branch's time."""
    local = timezone.localtime(when)
    return f'{local.hour % 12 or 12}:{local.minute:02d}{"am" if local.hour < 12 else "pm"}'
