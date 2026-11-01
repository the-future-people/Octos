"""
Who was in, and when.

A person is expected on a day when their shift says so (EmployeeShift
for that weekday), unless an override says otherwise: an ABSENCE
override means they were not expected, any other override moves their
start time. Approved leave (Employee status ON_LEAVE) is never counted
as absence.

Late means a first clock-in more than GRACE minutes after the start.
Clock-ins come from the clock-in log; for today, the user's
last_clock_in stands in when the log has nothing yet.

Signed in (an Octos portal session that day) is shown separately from
clocked in, as the owner asked: the two disagreeing is itself a signal.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from django.utils import timezone

from . import periods

GRACE = timedelta(minutes=10)

ON_TIME, LATE, ABSENT, LEAVE, OFF, NOT_YET = 'on', 'late', 'absent', 'leave', 'off', 'not_yet'
UNTRACKED = 'untracked'
LABEL = {ON_TIME: 'On time', LATE: 'Late', ABSENT: 'Absent', LEAVE: 'On leave',
         OFF: 'Day off', NOT_YET: 'Not in yet', UNTRACKED: 'Not tracked'}

# A branch whose people have no clock-in at all in this many days is not
# clocking in yet. Its attendance is shown as not tracked, never as
# everyone absent.
TRACKING_WINDOW_DAYS = 30


def tracked_branches(branch_ids) -> set:
    from apps.accounts.models import CustomUser, RFIDAccessLog
    since = timezone.now() - timedelta(days=TRACKING_WINDOW_DAYS)
    by_log = set(RFIDAccessLog.objects.filter(branch_id__in=branch_ids, action='CLOCK_IN',
                                              timestamp__gte=since)
                 .values_list('branch_id', flat=True))
    by_user = set(CustomUser.objects.filter(branch_id__in=branch_ids, last_clock_in__gte=since)
                  .values_list('branch_id', flat=True))
    return by_log | by_user


def staff(branch_ids):
    from apps.accounts.models import CustomUser
    return (CustomUser.objects
            .filter(branch_id__in=branch_ids, is_active=True,
                    employment_status='ACTIVE', role__isnull=False,
                    is_business_owner=False)
            .select_related('branch', 'role'))


def role_label(role) -> str:
    if not role:
        return ''
    for attr in ('display_name', 'label', 'title'):
        v = getattr(role, attr, '')
        if v:
            return v
    return role.name.replace('_', ' ').capitalize()


class Ledger:
    """Everything needed to say who was in on any day of a window, loaded once."""

    def __init__(self, users, first, last):
        from apps.accounts.models import RFIDAccessLog
        from apps.analytics.models import UserSession
        from apps.hr.models import Employee, EmployeeShift, ShiftOverride

        self.users = list(users)
        self.first, self.last = first, last
        uids = [u.pk for u in self.users]
        start, end = periods.bounds(first, last)

        self.employee = {e.user_id: e for e in Employee.objects.filter(user_id__in=uids)}
        emp_ids = [e.pk for e in self.employee.values()]

        self.shift = {}
        for s in EmployeeShift.objects.filter(employee_id__in=emp_ids, is_active=True):
            self.shift[(s.employee_id, s.day_of_week)] = s.start_time

        self.override = {}
        for o in ShiftOverride.objects.filter(employee_id__in=emp_ids, date__gte=first, date__lte=last):
            self.override[(o.employee_id, o.date)] = o

        self.clock = defaultdict(dict)       # uid -> {date: first clock-in}
        for log in (RFIDAccessLog.objects
                    .filter(employee_id__in=uids, action='CLOCK_IN',
                            timestamp__gte=start, timestamp__lt=end)
                    .order_by('timestamp')):
            d = timezone.localtime(log.timestamp).date()
            self.clock[log.employee_id].setdefault(d, log.timestamp)

        self.session = defaultdict(dict)     # uid -> {date: first sign-in}
        for s in (UserSession.objects
                  .filter(user_id__in=uids, started_at__gte=start, started_at__lt=end)
                  .order_by('started_at')):
            d = timezone.localtime(s.started_at).date()
            self.session[s.user_id].setdefault(d, s.started_at)

        self.tracked = tracked_branches({u.branch_id for u in self.users if u.branch_id})

        today = timezone.localdate()
        for u in self.users:
            if u.last_clock_in and timezone.localtime(u.last_clock_in).date() == today:
                self.clock[u.pk].setdefault(today, u.last_clock_in)

    def expected_start(self, user, day):
        emp = self.employee.get(user.pk)
        if not emp:
            return None
        o = self.override.get((emp.pk, day))
        if o:
            if o.override_type == 'ABSENCE':
                return None
            if o.override_start:
                return o.override_start
        return self.shift.get((emp.pk, day.weekday()))

    def status(self, user, day, now=None):
        now = now or timezone.now()
        emp = self.employee.get(user.pk)
        clocked = self.clock[user.pk].get(day)
        start_t = self.expected_start(user, day)
        if emp and emp.status == 'ON_LEAVE' and day == timezone.localdate():
            return LEAVE, clocked, start_t
        if user.branch_id not in self.tracked:
            return UNTRACKED, clocked, start_t
        if start_t is None:
            return (ON_TIME if clocked else OFF), clocked, None
        due = timezone.make_aware(datetime.combine(day, start_t)) + GRACE
        if clocked:
            return (LATE if clocked > due else ON_TIME), clocked, start_t
        if now < due:
            return NOT_YET, None, start_t
        return ABSENT, None, start_t

    def month_stats(self, user):
        """Attendance over the window: days expected, days in, late, average arrival."""
        expected = present = late = 0
        mins = []
        d = self.first
        while d <= self.last:
            st, clocked, start_t = self.status(user, d)
            if st in (ON_TIME, LATE, ABSENT):
                if start_t is not None:
                    expected += 1
                if st != ABSENT:
                    present += 1
                    lt = timezone.localtime(clocked)
                    mins.append(lt.hour * 60 + lt.minute)
                if st == LATE:
                    late += 1
            d += timedelta(days=1)
        avg = None
        if mins:
            m = round(sum(mins) / len(mins))
            avg = f'{m // 60:02d}:{m % 60:02d}'
        return {'expected': expected, 'present': min(present, expected) if expected else present,
                'attendance_pct': round(min(present, expected) / expected * 100) if expected else None,
                'late': late, 'average_arrival': avg}


def _fmt(dt):
    return timezone.localtime(dt).strftime('%H:%M') if dt else None


def person_row(ledger, u, day):
    st, clocked, start_t = ledger.status(u, day)
    return {
        'id': u.pk, 'name': u.full_name, 'role': role_label(u.role),
        'branch': u.branch.name if u.branch_id else '', 'branch_id': u.branch_id,
        'status': st, 'status_label': LABEL[st],
        'clocked_in': _fmt(clocked), 'shift_start': start_t.strftime('%H:%M') if start_t else None,
        'signed_in': _fmt(ledger.session[u.pk].get(day)),
    }


def today_counts(rows):
    c = defaultdict(int)
    for r in rows:
        c[r['status']] += 1
    present = c[ON_TIME] + c[LATE]
    return {'present': present, 'total': len(rows), 'late': c[LATE], 'absent': c[ABSENT],
            'leave': c[LEAVE], 'not_yet': c[NOT_YET], 'off': c[OFF],
            'untracked': c[UNTRACKED],
            'signed_in': sum(1 for r in rows if r['signed_in']),
            'tracking': c[UNTRACKED] < len(rows) or not rows}


def lens(scope, day) -> dict:
    users = list(staff(scope.branch_ids))
    first = day.replace(day=1)
    ledger = Ledger(users, first, day)
    rows = [person_row(ledger, u, day) for u in users]

    by_role = defaultdict(int)
    for r in rows:
        by_role[r['role']] += 1

    stats = [ledger.month_stats(u) for u in users]
    expected = sum(s['expected'] for s in stats)
    present = sum(s['present'] for s in stats)
    late_total = sum(s['late'] for s in stats)
    arrivals = [s['average_arrival'] for s in stats if s['average_arrival']]
    avg = None
    if arrivals:
        m = round(sum(int(a[:2]) * 60 + int(a[3:]) for a in arrivals) / len(arrivals))
        avg = f'{m // 60:02d}:{m % 60:02d}'

    openings = applicants = None
    try:
        from apps.hr.models import Applicant, JobPosition
        pos = JobPosition.objects.filter(branch_id__in=scope.branch_ids)
        for field, val in (('status', 'OPEN'), ('is_open', True), ('is_active', True)):
            try:
                openings = pos.filter(**{field: val}).count()
                break
            except Exception:
                continue
        try:
            applicants = Applicant.objects.filter(position__in=pos).count()
        except Exception:
            applicants = None
    except Exception:
        pass

    return {
        'people': rows,
        'today': today_counts(rows),
        'by_role': dict(by_role),
        'month': {'attendance_pct': round(present / expected * 100) if expected else None,
                  'average_arrival': avg, 'late': late_total},
        'openings': openings, 'applicants': applicants,
    }


def person(user_id, day) -> dict:
    from apps.accounts.models import CustomUser
    from apps.jobs.models import FinalCheck, Job, JobStep

    u = CustomUser.objects.select_related('branch', 'role').get(pk=user_id)
    first = day.replace(day=1)
    ledger = Ledger([u], first, day)
    row = person_row(ledger, u, day)
    stats = ledger.month_stats(u)

    calendar = []
    d = first
    while d <= day:
        st, clocked, _ = ledger.status(u, d)
        calendar.append({'date': d.isoformat(), 'status': st, 'clocked_in': _fmt(clocked)})
        d += timedelta(days=1)

    start, end = periods.bounds(first, day)
    handled = Job.objects.filter(intake_by=u, created_at__gte=start, created_at__lt=end
                                 ).exclude(status__in=['DRAFT', 'CANCELLED', 'VOIDED'])
    value = sum((j or 0) for j in handled.values_list('amount_paid', flat=True))
    sent_back = FinalCheck.objects.filter(step__done_by=u, outcome='SENT_BACK',
                                          checked_at__gte=start, checked_at__lt=end).count()
    overrides = JobStep.objects.filter(done_by=u, done_at__gte=start, done_at__lt=end
                                       ).exclude(done_override='').count()

    manager = None
    reports = []
    if u.branch_id:
        same = staff([u.branch_id]).exclude(pk=u.pk)
        bm = [x for x in same if x.role and x.role.name == 'BRANCH_MANAGER']
        if u.role and u.role.name == 'BRANCH_MANAGER':
            ledger2 = Ledger(list(same), day, day)
            reports = [person_row(ledger2, x, day) for x in same]
        elif bm:
            manager = {'id': bm[0].pk, 'name': bm[0].full_name}

    return {
        **row, 'phone': u.phone, 'email': u.email, 'month': stats,
        'calendar': calendar,
        'work': {'jobs': handled.count(), 'value': value},
        'mistakes': {'sent_back': sent_back, 'overrides': overrides, 'refunds': None},
        'manager': manager, 'reports': reports,
    }


def late_three_times(branch_ids, day):
    """People late 3 or more times this week, for the alert."""
    users = list(staff(branch_ids))
    first = day - timedelta(days=day.weekday())
    ledger = Ledger(users, first, day)
    out = []
    for u in users:
        n = 0
        d = first
        while d <= day:
            if ledger.status(u, d)[0] == LATE:
                n += 1
            d += timedelta(days=1)
        if n >= 3:
            out.append((u, n))
    return out
