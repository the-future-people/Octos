# apps/jobs/selectors/performance_selectors.py
"""
Performance selectors — branch performance aggregations.
Called by BranchPerformanceView. Never queries inline in views.
"""
from django.db.models import Sum, Count, Q
from django.db.models.functions import ExtractHour
from django.utils import timezone
from datetime import timedelta


def get_hourly_distribution(qs):
    hourly_raw = list(
        qs.annotate(hour=ExtractHour('created_at'))
        .values('hour')
        .annotate(count=Count('id'), revenue=Sum('amount_paid'))
        .order_by('hour')
    )
    hourly_map = {
        h['hour']: {'count': h['count'], 'revenue': float(h['revenue'] or 0)}
        for h in hourly_raw
    }
    return [
        {
            'hour':    h,
            'label':   f"{h % 12 or 12}{'am' if h < 12 else 'pm'}",
            'count':   hourly_map.get(h, {}).get('count',   0),
            'revenue': hourly_map.get(h, {}).get('revenue', 0),
        }
        for h in range(7, 20)
    ]


def get_service_breakdown(branch, since):
    from apps.jobs.models import JobLineItem
    services_raw = list(
        JobLineItem.objects.filter(
            job__branch=branch,
            job__created_at__gte=since,
            job__status='COMPLETE',
        ).values('service__name')
        .annotate(count=Count('id'), revenue=Sum('line_total'))
        .order_by('-revenue')[:10]
    )
    total = sum(float(s['revenue'] or 0) for s in services_raw)
    return [
        {
            'name':       s['service__name'],
            'count':      s['count'],
            'revenue':    float(s['revenue'] or 0),
            'percentage': round(float(s['revenue'] or 0) / total * 100, 1) if total else 0,
        }
        for s in services_raw
    ]


def get_staff_breakdown(qs):
    staff_raw = list(
        qs.values(
            'intake_by__first_name',
            'intake_by__last_name',
            'intake_by__id',
        ).annotate(
            total    = Count('id'),
            complete = Count('id', filter=Q(status='COMPLETE')),
            revenue  = Sum('amount_paid'),
        ).order_by('-total')
    )
    return [
        {
            'id':       s['intake_by__id'],
            'name':     f"{s['intake_by__first_name'] or ''} {s['intake_by__last_name'] or ''}".strip().title(),
            'total':    s['total'],
            'complete': s['complete'],
            'revenue':  float(s['revenue'] or 0),
            'rate':     round(s['complete'] / s['total'] * 100) if s['total'] else 0,
        }
        for s in staff_raw
    ]


def get_performance(branch, period='day'):
    now = timezone.now()
    since = {
        'day':   now.replace(hour=0, minute=0, second=0, microsecond=0),
        'week':  (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0),
        'month': now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
    }.get(period, now.replace(hour=0, minute=0, second=0, microsecond=0))

    from apps.jobs.models import Job
    qs = Job.objects.filter(branch=branch, created_at__gte=since)

    agg = qs.aggregate(
        total    = Count('id'),
        complete = Count('id', filter=Q(status='COMPLETE')),
        pending  = Count('id', filter=Q(status='PENDING_PAYMENT')),
        revenue  = Sum('amount_paid'),
        walkin   = Count('id', filter=Q(customer__isnull=True)),
    )

    hourly = get_hourly_distribution(qs)
    peak   = max(hourly, key=lambda x: x['count']) if hourly else None

    # Daily breakdown for week/month charts
    from django.db.models.functions import TruncDate
    daily = []
    if period in ('week', 'month'):
        daily_raw = list(
            qs.annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(count=Count('id'), revenue=Sum('amount_paid'))
            .order_by('day')
        )
        daily = [
            {
                'label':   d['day'].strftime('%-d %b'),
                'day':     d['day'].isoformat(),
                'count':   d['count'],
                'revenue': float(d['revenue'] or 0),
            }
            for d in daily_raw
        ]

    return {
        'period': period,
        'since':  since.isoformat(),
        'summary': {
            'total':    agg['total']    or 0,
            'complete': agg['complete'] or 0,
            'pending':  agg['pending']  or 0,
            'revenue':  float(agg['revenue'] or 0),
            'walkin':   agg['walkin']   or 0,
            'rate':     round((agg['complete'] or 0) / max(agg['total'] or 1, 1) * 100),
        },
        'hourly':   hourly,
        'daily':    daily,
        'peak':     peak,
        'services': get_service_breakdown(branch, since),
        'staff':    get_staff_breakdown(qs),
    }