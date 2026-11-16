"""
The attendant's Today screen (16 Nov 2026), in one call polled every 30 seconds.

  me        jobs today against their own usual (the 7-day average from
            get_personal_stats, at least 5), best day, streak, value, paid,
            jobs an hour
  needs     what to do next: front-desk work to take, pickups ready, chats
            Octos handed to a person, their own drafts to finish
  team      the branch's jobs today against a usual day here (the average of
            its last seven days with jobs), their share, the busiest hour
  jobs      their jobs today, newest first
  shift     opening, recording closing and sign-off, from the shift engine
  scans     customers who scanned the counter QR in the last 10 minutes

One call instead of six keeps the portal well inside the request limit.
"""
from datetime import datetime, time, timedelta

from django.db.models import Count, Min, Q
from django.db.models.functions import ExtractHour, TruncDate
from django.utils import timezone

NOT_PAID = ('DRAFT', 'PENDING_PAYMENT', 'CANCELLED', 'VOIDED', 'INTAKE_HELD')
NOT_COUNTED = ('DRAFT', 'CANCELLED', 'VOIDED')
SCAN_MINUTES = 10
USUAL_DAYS = 7
RECENT_JOBS = 6
STREAK_LOOKBACK = 60


def attendant_today(user, now=None):
    branch = user.branch
    now = now or timezone.now()
    day_start = timezone.make_aware(datetime.combine(timezone.localdate(now), time.min))
    return {
        'me': _me(user, branch, now, day_start),
        'needs': _needs(user, branch, now),
        'team': _team(user, branch, day_start),
        'jobs': _jobs(user, branch, day_start),
        'shift': _shift(branch),
        'scans': _scans(branch, now),
    }


# ── Me ───────────────────────────────────────────────────────────────────

def _me(user, branch, now, day_start):
    from apps.finance.models import DailySalesSheet
    from apps.jobs.models import Job
    from apps.jobs.selectors.stats_selectors import get_personal_stats

    sheet = DailySalesSheet.objects.filter(branch=branch, date=timezone.localdate(now)).first()
    personal = get_personal_stats(user, branch, sheet.id if sheet else None) if sheet else {}

    mine = (Job.objects.filter(branch=branch, intake_by=user, created_at__gte=day_start)
            .exclude(status__in=NOT_COUNTED))
    total = mine.count()
    paid = mine.exclude(status__in=NOT_PAID).count()
    value = sum(float(j or 0) for j in mine.values_list('estimated_cost', flat=True))
    from apps.accounts.profiles import photo_url
    return {
        'first_name': user.first_name,
        'photo_url': photo_url(user),
        'total': total,
        'target': personal.get('daily_target') or 10,
        'value': round(value, 2),
        'paid': paid,
        'per_hour': personal.get('jobs_per_hour'),
        'best': personal.get('personal_best'),
        'best_date': personal.get('personal_best_date'),
        'streak': _streak(user, branch, personal.get('daily_target') or 10, total, day_start),
        'sheet_open': bool(sheet and sheet.status == 'OPEN'),
        'sheet_number': getattr(sheet, 'sheet_number', None),
    }


def _streak(user, branch, target, today_total, day_start):
    """
    Days in a row they reached their target, counting today once they have.
    Days the branch recorded nothing (Sundays, holidays) don't break it.
    """
    from apps.jobs.models import Job

    since = day_start - timedelta(days=STREAK_LOOKBACK)
    live = Job.objects.filter(branch=branch, created_at__gte=since, created_at__lt=day_start).exclude(status__in=NOT_COUNTED)
    open_days = set(live.annotate(day=TruncDate('created_at')).values_list('day', flat=True))
    mine = dict(live.filter(intake_by=user).annotate(day=TruncDate('created_at'))
                .values('day').annotate(n=Count('id')).values_list('day', 'n'))
    streak = 1 if today_total >= target else 0
    for day in sorted(open_days, reverse=True):
        if mine.get(day, 0) >= target:
            streak += 1
        else:
            break
    return streak


# ── Needs you now ────────────────────────────────────────────────────────

def _needs(user, branch, now):
    return {
        'desk': _desk(branch, now),
        'pickups': _pickups(branch),
        'chats': _chats(user),
        'drafts': _drafts(user, branch, now),
    }


def _desk(branch, now):
    from apps.jobs.services import front_desk

    waiting = [j for j in front_desk.queue(branch) if not j.desk_taken_by_id]
    if not waiting:
        return {'count': 0}
    first = min(waiting, key=lambda j: front_desk.landed_at(j, now))
    return {
        'count': len(waiting),
        'oldest_minutes': int((now - front_desk.landed_at(first, now)).total_seconds() // 60),
        'first': _summary(first),
    }


def _pickups(branch):
    from apps.jobs.models import Job, JobStatusLog
    from apps.jobs.selectors.workload_selectors import workload_filter

    ready = list(Job.objects.filter(branch=branch).filter(workload_filter('ready_for_pickup', timezone.now()))
                 .values_list('id', flat=True))
    if not ready:
        return {'count': 0}
    since = (JobStatusLog.objects.filter(job_id__in=ready, axis=JobStatusLog.Axis.WORK, to_status='DONE')
             .aggregate(oldest=Min('transitioned_at'))['oldest'])
    return {'count': len(ready), 'oldest_ready_at': since.isoformat() if since else None}


def _chats(user):
    from apps.communications.models import Conversation
    from apps.communications.services.access import visible_conversations

    asked = (visible_conversations(user)
             .filter(handled_by=Conversation.STAFF).exclude(handoff_reason='')
             .exclude(status__in=[Conversation.RESOLVED, Conversation.SPAM])
             .order_by('handled_since'))
    first = asked.first()
    if first is None:
        return {'count': 0}
    return {
        'count': asked.count(),
        'first_name': first.contact_name or first.contact_phone or 'A customer',
        'first_id': first.pk,
        'since': first.handled_since.isoformat() if first.handled_since else None,
    }


def _drafts(user, branch, now):
    from apps.jobs.models import Job

    drafts = Job.objects.filter(branch=branch, intake_by=user, status=Job.DRAFT,
                                draft_expires_at__gt=now).order_by('-updated_at')
    first = drafts.first()
    if first is None:
        return {'count': 0}
    return {'count': drafts.count(), 'first': _summary(first)}


# ── Team today ───────────────────────────────────────────────────────────

def _team(user, branch, day_start):
    from apps.jobs.models import Job

    live = Job.objects.filter(branch=branch).exclude(status__in=NOT_COUNTED)
    today = live.filter(created_at__gte=day_start)
    days = (live.filter(created_at__gte=day_start - timedelta(days=USUAL_DAYS), created_at__lt=day_start)
            .annotate(day=TruncDate('created_at')).values('day').annotate(n=Count('id')))
    counts = [d['n'] for d in days]
    hours = (today.annotate(hour=ExtractHour('created_at', tzinfo=timezone.get_current_timezone()))
             .values('hour').annotate(n=Count('id')).order_by('-n', 'hour').first())
    return {
        'total': today.count(),
        'mine': today.filter(intake_by=user).count(),
        'usual': round(sum(counts) / len(counts)) if counts else None,
        'busiest_hour': hours['hour'] if hours else None,
    }


# ── My jobs today ────────────────────────────────────────────────────────

def _jobs(user, branch, day_start):
    from apps.jobs.models import Job

    rows = (Job.objects.filter(branch=branch, intake_by=user, created_at__gte=day_start)
            .exclude(status__in=NOT_COUNTED).select_related('customer')
            .prefetch_related('line_items__service').order_by('-created_at')[:RECENT_JOBS])
    return [{**_summary(job),
             'at': job.created_at.isoformat(),
             'amount': str(job.estimated_cost or 0),
             'paid': job.status not in NOT_PAID}
            for job in rows]


def _summary(job):
    from apps.jobs.services.labels import for_whom

    who, from_chat = for_whom(job)
    lines = list(job.line_items.all())
    if lines:
        first = lines[0]
        what = first.service.name if first.service_id else job.title
        if first.quantity and first.quantity > 1:
            what = f'{what} × {first.quantity}'
        if len(lines) > 1:
            what = f'{what} +{len(lines) - 1} more'
    else:
        what = job.title
    return {'id': job.pk, 'who': who, 'from_chat': from_chat, 'what': what}


# ── Shift and scans ──────────────────────────────────────────────────────

def _shift(branch):
    from apps.finance.attendant_signoff_engine import AttendantSignOffEngine
    try:
        t = AttendantSignOffEngine(branch).timing()
    except Exception:
        return None
    return {'opens': t['shift_start'].isoformat(),
            'recording_closes': t['recording_closes_at'].isoformat(),
            'sign_off': t['deadline'].isoformat()}


def _scans(branch, now):
    """Customers who scanned the counter QR (or said they're at the counter) just now."""
    from apps.spine import kinds
    from apps.spine.models import Event, Visit

    events = (Event.objects.filter(kind=kinds.PRESENCE_COUNTER, branch=branch,
                                   occurred_at__gte=now - timedelta(minutes=SCAN_MINUTES))
              .select_related('conversation', 'customer').order_by('-occurred_at'))
    month_start = timezone.make_aware(datetime.combine(timezone.localdate(now).replace(day=1), time.min))
    seen, rows = set(), []
    for e in events:
        if e.conversation_id in seen or not e.conversation_id:
            continue
        seen.add(e.conversation_id)
        chat = e.conversation
        name = (e.customer.display_name if e.customer_id else '') or chat.contact_name or chat.contact_phone or 'A customer'
        rows.append({
            'id': e.pk,
            'name': name,
            'conversation_id': e.conversation_id,
            'customer_id': e.customer_id,
            'phone': chat.contact_phone or '',
            'at': e.occurred_at.isoformat(),
            'verified': bool((e.payload or {}).get('verified')),
            'visits_this_month': Visit.objects.filter(conversation_id=e.conversation_id,
                                                      opened_at__gte=month_start).count(),
        })
    return rows
