# apps/jobs/selectors/stats_selectors.py
"""
Stats selectors — pure read functions for job statistics.

These are the source of truth for all stats aggregations.
Views call these; they never query inline.
"""

from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta


def get_branch_stats(branch, sheet_id=None, period=None, job_type=None) -> dict:
    """
    Branch-wide job counts and revenue for a given sheet (or all time).
    Called by JobStatsView.
    """
    from django.core.cache import cache
    from apps.jobs.models import Job, JobHalt
    from django.db import models

    if sheet_id and not period and not job_type:
        _cache_key = f'jobstats:branch:{branch.pk}:sheet:{sheet_id}'
        _cached = cache.get(_cache_key)
        if _cached is not None:
            return _cached

    qs = Job.objects.filter(branch=branch)
    if sheet_id:
        qs = qs.filter(daily_sheet_id=sheet_id)
    if job_type:
        qs = qs.filter(job_type=job_type)
    if period:
        since = {
            'day':   timezone.now().replace(hour=0, minute=0, second=0, microsecond=0),
            'week':  (timezone.now() - timedelta(days=timezone.now().weekday())).replace(hour=0, minute=0, second=0, microsecond=0),
            'month': timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            'year':  timezone.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
        }.get(period)
        if since:
            qs = qs.filter(created_at__gte=since)

    # Cancelled jobs are excluded from every axis counter. A cancelled job
    # still carries whatever axis states it had when it was cancelled, and
    # counting it as "awaiting payment" would put dead work in a live queue.
    live = ~Q(status='CANCELLED')

    totals = qs.aggregate(
        total       = Count('id'),
        complete    = Count('id', filter=Q(status='COMPLETE')),
        in_progress = Count('id', filter=Q(status='IN_PROGRESS')),
        pending     = Count('id', filter=Q(status='PENDING_PAYMENT')),
        cancelled   = Count('id', filter=Q(status='CANCELLED')),
        routed      = Count('id', filter=Q(is_routed=True)),
        revenue     = Sum('amount_paid', filter=Q(status='COMPLETE')),

        # ── Lifecycle axes ────────────────────────────────────────
        awaiting_payment = Count('id', filter=live & ~Q(payment_state='SETTLED')),
        in_production    = Count('id', filter=live & Q(
            work_state__in=['RECEIVED', 'IN_PRODUCTION',
                            'FINISHING', 'QUALITY_CHECK'],
        )),
        ready_for_pickup = Count('id', filter=live & Q(
            work_state='DONE',
            handover_state='AWAITING_COLLECTION',
        )),
        out_for_delivery = Count('id', filter=live & Q(
            handover_state='OUT_FOR_DELIVERY',
        )),
        handed_over      = Count('id', filter=live & Q(
            handover_state='HANDED_OVER',
        )),
        # Not a join filter: a LEFT JOIN gives a NULL resumed_at to jobs
        # with no halts at all, so halts__resumed_at__isnull=True matched
        # every job that had never been halted.
        halted           = Count('id', filter=live & Q(
            pk__in=JobHalt.objects.filter(
                resumed_at__isnull=True,
            ).values('job_id'),
        )),
    )

    registered = qs.filter(customer__isnull=False).count()
    walkin     = (totals['total'] or 0) - registered

    result = {
        'total'      : totals['total']      or 0,
        'complete'   : totals['complete']   or 0,
        'in_progress': totals['in_progress'] or 0,
        'pending'    : totals['pending']    or 0,
        'cancelled'  : totals['cancelled']  or 0,
        'routed'     : totals['routed']     or 0,
        'revenue'    : str(totals['revenue'] or 0),
        'registered' : registered,
        'walkin'     : walkin,

        'awaiting_payment': totals['awaiting_payment'] or 0,
        'in_production'   : totals['in_production']    or 0,
        'ready_for_pickup': totals['ready_for_pickup'] or 0,
        'out_for_delivery': totals['out_for_delivery'] or 0,
        'handed_over'     : totals['handed_over']      or 0,
        'halted'          : totals['halted']           or 0,
    }
    if sheet_id and not period and not job_type:
        cache.set(_cache_key, result, 90)
    return result


def get_personal_stats(user, branch, sheet_id=None) -> dict:
    """
    Personal attendant stats for a given sheet (or today).
    Called by JobStatsView. Never raises — returns {} on any error
    so branch stats are never broken by a personal stats failure.
    """
    from django.core.cache import cache
    from apps.jobs.models import Job
    from apps.finance.models import DailySalesSheet

    if sheet_id:
        _personal_key = f'jobstats:personal:{user.pk}:sheet:{sheet_id}'
        _cached = cache.get(_personal_key)
        if _cached is not None:
            return _cached

    today = timezone.localdate()
    now   = timezone.now()

    # ── My jobs on this sheet ─────────────────────────────────────────
    my_qs = Job.objects.filter(branch=branch, intake_by=user)
    if sheet_id:
        my_qs = my_qs.filter(daily_sheet_id=sheet_id)

    my_agg = my_qs.aggregate(
        total     = Count('id'),
        confirmed = Count('id', filter=Q(status='COMPLETE')),
        my_value  = Sum('estimated_cost'),
    )
    my_total     = my_agg['total']     or 0
    my_confirmed = my_agg['confirmed'] or 0
    my_value     = float(my_agg['my_value'] or 0)
    my_rate      = round(my_confirmed / my_total * 100) if my_total else 0

    # ── Sheet open time → jobs per hour ──────────────────────────────
    jobs_per_hour = None
    sheet_number  = None
    try:
        sheet = DailySalesSheet.objects.get(pk=sheet_id) if sheet_id else \
                DailySalesSheet.objects.get(branch=branch, date=today)
        sheet_number = sheet.id

        if sheet.created_at:
            hours_elapsed = max(
                (now - sheet.created_at).total_seconds() / 3600, 0.25
            )
            jobs_per_hour = round(my_total / hours_elapsed, 1)
    except Exception:
        pass

    # ── Yesterday completion rate ────────────────────────────────────
    yesterday_rate = None
    try:
        yesterday = today - timedelta(days=1)
        ysheet    = DailySalesSheet.objects.get(branch=branch, date=yesterday)
        y_qs      = Job.objects.filter(
            branch=branch, intake_by=user, daily_sheet=ysheet
        )
        y_agg = y_qs.aggregate(
            total     = Count('id'),
            confirmed = Count('id', filter=Q(status='COMPLETE')),
        )
        if y_agg['total']:
            yesterday_rate = round(
                (y_agg['confirmed'] or 0) / y_agg['total'] * 100
            )
    except Exception:
        pass

    # ── Personal best (all time) ─────────────────────────────────────
    personal_best      = None
    personal_best_date = None
    try:
        from django.db.models.functions import TruncDate
        daily_counts = (
            Job.objects
            .filter(branch=branch, intake_by=user)
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(count=Count('id'))
            .order_by('-count')
            .first()
        )
        if daily_counts:
            personal_best      = daily_counts['count']
            personal_best_date = daily_counts['day'].strftime('%-d %b')
    except Exception:
        pass

    # ── Top service this week ────────────────────────────────────────
    top_service       = None
    top_service_count = None
    try:
        week_start = today - timedelta(days=today.weekday())
        from apps.jobs.models import JobLineItem
        top = (
            JobLineItem.objects
            .filter(
                job__branch=branch,
                job__intake_by=user,
                job__created_at__date__gte=week_start,
            )
            .values('service__name')
            .annotate(cnt=Count('id'))
            .order_by('-cnt')
            .first()
        )
        if top:
            top_service       = top['service__name']
            top_service_count = top['cnt']
    except Exception:
        pass

    # ── Week daily counts (Mon–today) ────────────────────────────────
    week_daily_counts = []
    try:
        week_start = today - timedelta(days=today.weekday())
        day_names  = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        for i in range(6):
            d     = week_start + timedelta(days=i)
            count = Job.objects.filter(
                branch=branch, intake_by=user,
                created_at__date=d,
            ).count()
            week_daily_counts.append({
                'day'      : day_names[i],
                'date'     : d.isoformat(),
                'count'    : count,
                'is_today' : d == today,
                'is_future': d > today,
            })
    except Exception:
        pass

    # ── Streak — consecutive 100% completion days ────────────────────
    streak      = 0
    streak_days = []
    try:
        day_names_short = ['M', 'T', 'W', 'T', 'F', 'S']
        week_start      = today - timedelta(days=today.weekday())

        for i in range(6):
            d = week_start + timedelta(days=i)
            if d > today:
                streak_days.append({'label': day_names_short[i], 'state': 'future'})
                continue

            d_qs  = Job.objects.filter(
                branch=branch, intake_by=user, created_at__date=d
            )
            d_agg = d_qs.aggregate(
                total     = Count('id'),
                confirmed = Count('id', filter=Q(status='COMPLETE')),
            )
            d_total = d_agg['total'] or 0
            d_conf  = d_agg['confirmed'] or 0
            hit     = d_total > 0 and d_conf == d_total

            streak_days.append({
                'label'   : day_names_short[i],
                'state'   : 'hit' if hit else ('miss' if d_total > 0 else 'empty'),
                'is_today': d == today,
            })

        for i in range(today.weekday(), -1, -1):
            day_entry = streak_days[i]
            if day_entry['state'] == 'hit' or (day_entry['is_today'] and my_rate == 100):
                streak += 1
            else:
                break
    except Exception:
        pass

    # ── Daily target — rolling 7-day average ─────────────────────────
    daily_target = 10  # fallback
    try:
        seven_days_ago = today - timedelta(days=7)
        past_counts    = (
            Job.objects
            .filter(
                branch=branch, intake_by=user,
                created_at__date__gte=seven_days_ago,
                created_at__date__lt=today,
            )
            .values('created_at__date')
            .annotate(count=Count('id'))
        )
        if past_counts:
            avg          = sum(d['count'] for d in past_counts) / len(past_counts)
            daily_target = max(int(round(avg)), 5)
    except Exception:
        pass

    _result = {
        'my_total'          : my_total,
        'my_confirmed'      : my_confirmed,
        'my_value'          : round(my_value, 2),
        'my_rate'           : my_rate,
        'jobs_per_hour'     : jobs_per_hour,
        'yesterday_rate'    : yesterday_rate,
        'personal_best'     : personal_best,
        'personal_best_date': personal_best_date,
        'top_service'       : top_service,
        'top_service_count' : top_service_count,
        'week_daily_counts' : week_daily_counts,
        'streak'            : streak,
        'streak_days'       : streak_days,
        'daily_target'      : daily_target,
        'sheet_number'      : sheet_number,
    }
    if sheet_id:
        cache.set(_personal_key, _result, 90)
    return _result

def get_active_workload(branch) -> dict:
    """
    Active workload counts for the BM Overview command centre.
    Single aggregation query — cached 60s per branch.
    """
    from django.core.cache import cache
    from apps.jobs.models import Job
    from django.utils import timezone

    cache_key = f'workload:branch:{branch.pk}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    now = timezone.now()

    qs = Job.objects.filter(branch=branch)

    agg = qs.aggregate(
        pending_payment    = Count('id', filter=Q(status='PENDING_PAYMENT')),
        in_production      = Count('id', filter=Q(
            status__in=['CONFIRMED', 'IN_PROGRESS'],
            job_type__in=['PRODUCTION', 'DESIGN'],
        )),
        ready_for_pickup   = Count('id', filter=Q(
            status='READY',
            job_type__in=['PRODUCTION', 'DESIGN'],
        )),
        awaiting_feedback  = Count('id', filter=Q(
            status__in=['SAMPLE_SENT', 'REVISION_REQUESTED'],
        )),
        overdue            = Count('id', filter=Q(
            deadline__lt=now,
            status__in=['CONFIRMED', 'IN_PROGRESS', 'READY', 'SAMPLE_SENT', 'REVISION_REQUESTED'],
        )),
    )

    # Oldest pending payment job age in minutes
    oldest_pending = qs.filter(
        status='PENDING_PAYMENT'
    ).order_by('created_at').values_list('created_at', flat=True).first()

    oldest_pending_mins = None
    if oldest_pending:
        oldest_pending_mins = int((now - oldest_pending).total_seconds() / 60)

    result = {
        'pending_payment'   : agg['pending_payment']   or 0,
        'in_production'     : agg['in_production']     or 0,
        'ready_for_pickup'  : agg['ready_for_pickup']  or 0,
        'awaiting_feedback' : agg['awaiting_feedback'] or 0,
        'overdue'           : agg['overdue']           or 0,
        'oldest_pending_mins': oldest_pending_mins,
    }
    cache.set(cache_key, result, 60)
    return result