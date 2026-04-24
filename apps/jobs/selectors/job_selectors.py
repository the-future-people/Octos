# apps/jobs/selectors/job_selectors.py
"""
Job history selectors — pure read functions for drill-down history views.

The four level functions (year/month/week/day) are the source of truth
for JobHistoryView. Helper functions (_agg, _pct_change, _week_ranges)
are module-level utilities used only by this module.
"""

from datetime import date, timedelta
from django.db.models import Sum, Count, Q
from django.db import models


# ── Helpers ───────────────────────────────────────────────────────────────────

def _agg(qs) -> dict:
    """Aggregate a queryset into KPI numbers."""
    result = qs.aggregate(
        total    = Count('id'),
        complete = Count('id', filter=Q(status='COMPLETE')),
        pending  = Count('id', filter=Q(status='PENDING_PAYMENT')),
        revenue  = Sum('amount_paid', filter=Q(status='COMPLETE')),
    )
    total    = result['total']    or 0
    complete = result['complete'] or 0
    pending  = result['pending']  or 0
    revenue  = float(result['revenue'] or 0)
    rate     = round(complete / total * 100, 1) if total else 0
    return {
        'total'   : total,
        'complete': complete,
        'pending' : pending,
        'revenue' : revenue,
        'rate'    : rate,
    }


def _pct_change(current, previous):
    """Compute % change between two values."""
    if not previous:
        return None
    change = round((current - previous) / previous * 100, 1)
    return f"+{change}%" if change >= 0 else f"{change}%"


def _week_ranges(year, month) -> list:
    """Return list of (week_num, start_date, end_date) for Mon-Sat weeks in a month."""
    import calendar

    first_day = date(year, month, 1)
    last_day  = date(year, month, calendar.monthrange(year, month)[1])

    weeks   = []
    current = first_day
    while current.weekday() != 0:
        current -= timedelta(days=1)

    week_num = 1
    while current <= last_day:
        week_start = current
        week_end   = min(current + timedelta(days=5), last_day)
        if week_end >= first_day:
            weeks.append((week_num, week_start, week_end))
            week_num += 1
        current += timedelta(days=7)

    return weeks


# ── Level selectors ───────────────────────────────────────────────────────────

def get_year_level(base_qs, branch) -> dict:
    """Year-level drill-down: KPIs, trend, bar, heatmap, items."""
    current_year = date.today().year

    year_set = set(d.year for d in base_qs.dates('created_at', 'year')) | {current_year}
    years    = sorted(year_set, reverse=True)

    cur_qs  = base_qs.filter(created_at__year=current_year)
    prev_qs = base_qs.filter(created_at__year=current_year - 1)
    cur     = _agg(cur_qs)
    prev    = _agg(prev_qs)

    kpis = {
        'total'  : {'value': cur['total'],   'change': _pct_change(cur['total'],   prev['total'])},
        'revenue': {'value': cur['revenue'],  'change': _pct_change(cur['revenue'], prev['revenue'])},
        'pending': {'value': cur['pending'],  'change': _pct_change(cur['pending'], prev['pending'])},
        'rate'   : {'value': cur['rate'],     'change': _pct_change(cur['rate'],    prev['rate'])},
    }

    trend_labels  = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    trend_jobs    = []
    trend_revenue = []
    for m in range(1, 13):
        mqs = cur_qs.filter(created_at__month=m)
        agg = _agg(mqs)
        trend_jobs.append(agg['total'])
        trend_revenue.append(agg['revenue'])

    bar_labels = [str(y) for y in sorted(years)]
    bar_data   = [_agg(base_qs.filter(created_at__year=y))['total'] for y in sorted(years)]

    heatmap = []
    start   = date(current_year, 1, 1)
    for w in range(52):
        week_start = start + timedelta(weeks=w)
        week_end   = week_start + timedelta(days=6)
        count = cur_qs.filter(
            created_at__date__gte=week_start,
            created_at__date__lte=week_end,
        ).count()
        heatmap.append({'week': w + 1, 'count': count})

    items = []
    for y in years:
        agg = _agg(base_qs.filter(created_at__year=y))
        items.append({
            'label'  : str(y),
            'year'   : y,
            'total'  : agg['total'],
            'revenue': agg['revenue'],
            'rate'   : agg['rate'],
        })

    return {
        'level'  : 'year',
        'kpis'   : kpis,
        'trend'  : {'labels': trend_labels, 'jobs': trend_jobs, 'revenue': trend_revenue},
        'bar'    : {'labels': bar_labels,   'data': bar_data},
        'heatmap': heatmap,
        'items'  : items,
    }


def get_month_level(base_qs, branch, year) -> dict:
    """Month-level drill-down: KPIs, trend, bar, heatmap, items."""
    import calendar

    month_names = ['Jan','Feb','Mar','Apr','May','Jun',
                   'Jul','Aug','Sep','Oct','Nov','Dec']

    cur_qs  = base_qs.filter(created_at__year=year)
    prev_qs = base_qs.filter(created_at__year=year - 1)
    cur     = _agg(cur_qs)
    prev    = _agg(prev_qs)

    kpis = {
        'total'  : {'value': cur['total'],   'change': _pct_change(cur['total'],   prev['total'])},
        'revenue': {'value': cur['revenue'],  'change': _pct_change(cur['revenue'], prev['revenue'])},
        'pending': {'value': cur['pending'],  'change': _pct_change(cur['pending'], prev['pending'])},
        'rate'   : {'value': cur['rate'],     'change': _pct_change(cur['rate'],    prev['rate'])},
    }

    trend_jobs    = []
    trend_revenue = []
    for m in range(1, 13):
        mqs = cur_qs.filter(created_at__month=m)
        agg = _agg(mqs)
        trend_jobs.append(agg['total'])
        trend_revenue.append(agg['revenue'])

    heatmap = []
    start   = date(year, 1, 1)
    for w in range(52):
        week_start = start + timedelta(weeks=w)
        week_end   = week_start + timedelta(days=6)
        count = cur_qs.filter(
            created_at__date__gte=week_start,
            created_at__date__lte=week_end,
        ).count()
        heatmap.append({'week': w + 1, 'count': count})

    items = []
    for m in range(1, 13):
        mqs = cur_qs.filter(created_at__month=m)
        agg = _agg(mqs)
        if agg['total'] > 0 or m <= date.today().month:
            items.append({
                'label'  : month_names[m - 1],
                'year'   : year,
                'month'  : m,
                'total'  : agg['total'],
                'revenue': agg['revenue'],
                'rate'   : agg['rate'],
            })

    return {
        'level'  : 'month',
        'year'   : year,
        'kpis'   : kpis,
        'trend'  : {'labels': month_names, 'jobs': trend_jobs, 'revenue': trend_revenue},
        'bar'    : {'labels': month_names, 'data': trend_jobs[:]},
        'heatmap': heatmap,
        'items'  : items,
    }


def get_week_level(base_qs, branch, year, month) -> dict:
    """Week-level drill-down: KPIs, trend, bar, heatmap, items."""
    import calendar

    month_names = ['January','February','March','April','May','June',
                   'July','August','September','October','November','December']

    cur_qs     = base_qs.filter(created_at__year=year, created_at__month=month)
    prev_month = month - 1 if month > 1 else 12
    prev_year  = year if month > 1 else year - 1
    prev_qs    = base_qs.filter(created_at__year=prev_year, created_at__month=prev_month)
    cur        = _agg(cur_qs)
    prev       = _agg(prev_qs)

    kpis = {
        'total'  : {'value': cur['total'],   'change': _pct_change(cur['total'],   prev['total'])},
        'revenue': {'value': cur['revenue'],  'change': _pct_change(cur['revenue'], prev['revenue'])},
        'pending': {'value': cur['pending'],  'change': _pct_change(cur['pending'], prev['pending'])},
        'rate'   : {'value': cur['rate'],     'change': _pct_change(cur['rate'],    prev['rate'])},
    }

    weeks         = _week_ranges(year, month)
    days_in_month = calendar.monthrange(year, month)[1]
    trend_labels  = [str(d) for d in range(1, days_in_month + 1)]
    trend_jobs    = []
    trend_revenue = []
    for d in range(1, days_in_month + 1):
        agg = _agg(cur_qs.filter(created_at__day=d))
        trend_jobs.append(agg['total'])
        trend_revenue.append(agg['revenue'])

    bar_labels = [f"Week {w[0]}" for w in weeks]
    bar_data   = [
        cur_qs.filter(created_at__date__gte=ws, created_at__date__lte=we).count()
        for _, ws, we in weeks
    ]

    heatmap = []
    for _, ws, we in weeks:
        week_row = []
        current  = ws
        while current <= we:
            count = cur_qs.filter(created_at__date=current).count()
            week_row.append({'date': current.isoformat(), 'count': count})
            current += timedelta(days=1)
        heatmap.append(week_row)

    items = []
    for wnum, ws, we in weeks:
        wqs = cur_qs.filter(created_at__date__gte=ws, created_at__date__lte=we)
        agg = _agg(wqs)
        items.append({
            'label'  : f"Week {wnum}",
            'week'   : wnum,
            'year'   : year,
            'month'  : month,
            'start'  : ws.isoformat(),
            'end'    : we.isoformat(),
            'total'  : agg['total'],
            'revenue': agg['revenue'],
            'rate'   : agg['rate'],
        })

    return {
        'level'     : 'week',
        'year'      : year,
        'month'     : month,
        'month_name': month_names[month - 1],
        'kpis'      : kpis,
        'trend'     : {'labels': trend_labels, 'jobs': trend_jobs, 'revenue': trend_revenue},
        'bar'       : {'labels': bar_labels,   'data': bar_data},
        'heatmap'   : heatmap,
        'items'     : items,
    }


def get_day_level(base_qs, branch, year, month, week) -> dict:
    """Day-level drill-down: KPIs, trend, bar, heatmap, items with sheet info."""
    import calendar as cal
    from apps.finance.models import DailySalesSheet

    weeks  = _week_ranges(year, month)
    target = next((w for w in weeks if w[0] == week), None)
    if not target:
        return None  # caller returns 400

    _, week_start, week_end = target

    first_day_of_month = date(year, month, 1)
    last_day_of_month  = date(year, month, cal.monthrange(year, month)[1])
    effective_start    = max(week_start, first_day_of_month)
    effective_end      = min(week_end,   last_day_of_month)

    cur_qs  = base_qs.filter(
        created_at__date__gte=effective_start,
        created_at__date__lte=effective_end,
    )
    prev_start = effective_start - timedelta(days=7)
    prev_end   = effective_end   - timedelta(days=7)
    prev_qs    = base_qs.filter(
        created_at__date__gte=prev_start,
        created_at__date__lte=prev_end,
    )
    cur  = _agg(cur_qs)
    prev = _agg(prev_qs)

    kpis = {
        'total'  : {'value': cur['total'],   'change': _pct_change(cur['total'],   prev['total'])},
        'revenue': {'value': cur['revenue'],  'change': _pct_change(cur['revenue'], prev['revenue'])},
        'pending': {'value': cur['pending'],  'change': _pct_change(cur['pending'], prev['pending'])},
        'rate'   : {'value': cur['rate'],     'change': _pct_change(cur['rate'],    prev['rate'])},
    }

    trend_labels  = [f"{h:02d}:00" for h in range(8, 20)]
    trend_jobs    = [cur_qs.filter(created_at__hour=h).count() for h in range(8, 20)]
    trend_revenue = [
        float(cur_qs.filter(
            created_at__hour=h, status='COMPLETE'
        ).aggregate(r=Sum('amount_paid'))['r'] or 0)
        for h in range(8, 20)
    ]

    bar_labels = []
    bar_data   = []
    current    = effective_start
    while current <= effective_end:
        bar_labels.append(current.strftime('%a %d'))
        bar_data.append(cur_qs.filter(created_at__date=current).count())
        current += timedelta(days=1)

    heatmap = []
    current = effective_start
    while current <= effective_end:
        day_row = []
        for h in range(8, 20):
            count = cur_qs.filter(
                created_at__date=current,
                created_at__hour=h,
            ).count()
            day_row.append({'hour': h, 'count': count})
        heatmap.append({'date': current.isoformat(), 'hours': day_row})
        current += timedelta(days=1)

    items   = []
    current = effective_start
    while current <= effective_end:
        dqs = cur_qs.filter(created_at__date=current)
        agg = _agg(dqs)
        try:
            sheet        = DailySalesSheet.objects.get(branch=branch, date=current)
            sheet_id     = sheet.id
            sheet_status = sheet.status
        except DailySalesSheet.DoesNotExist:
            sheet_id     = None
            sheet_status = None

        items.append({
            'date'        : current.isoformat(),
            'label'       : current.strftime('%a %d %b'),
            'total'       : agg['total'],
            'revenue'     : agg['revenue'],
            'complete'    : agg['complete'],
            'pending'     : agg['pending'],
            'rate'        : agg['rate'],
            'sheet_id'    : sheet_id,
            'sheet_status': sheet_status,
        })
        current += timedelta(days=1)

    return {
        'level'     : 'day',
        'year'      : year,
        'month'     : month,
        'week'      : week,
        'week_start': effective_start.isoformat(),
        'week_end'  : effective_end.isoformat(),
        'kpis'      : kpis,
        'trend'     : {'labels': trend_labels, 'jobs': trend_jobs, 'revenue': trend_revenue},
        'bar'       : {'labels': bar_labels,   'data': bar_data},
        'heatmap'   : heatmap,
        'items'     : items,
    }