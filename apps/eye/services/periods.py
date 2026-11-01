"""
Time windows. Every period is compared with the one before it, of the
same length: today with yesterday, this week so far with the same days
last week, this month so far with the same days last month.
"""

from datetime import date, datetime, time, timedelta

from django.utils import timezone

PERIODS = ('today', 'week', 'month')


def parse_day(raw) -> date:
    if raw:
        try:
            return date.fromisoformat(str(raw))
        except ValueError:
            pass
    return timezone.localdate()


def start_of(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


def bounds(first: date, last: date):
    """[start of first, start of the day after last)."""
    return start_of(first), start_of(last + timedelta(days=1))


def window(name: str, day: date):
    """
    (first_day, last_day, prev_first, prev_last, label) for a period
    ending on `day`.
    """
    if name == 'week':
        first = day - timedelta(days=day.weekday())
        span = (day - first).days
        prev_first = first - timedelta(days=7)
        return first, day, prev_first, prev_first + timedelta(days=span), 'last week'
    if name == 'month':
        first = day.replace(day=1)
        prev_last_month_end = first - timedelta(days=1)
        prev_first = prev_last_month_end.replace(day=1)
        span = (day - first).days
        prev_last = min(prev_first + timedelta(days=span), prev_last_month_end)
        return first, day, prev_first, prev_last, 'last month'
    prev = day - timedelta(days=1)
    return day, day, prev, prev, 'yesterday'


def change(now, before):
    """Percentage change, or None where there is nothing to compare with."""
    try:
        now, before = float(now or 0), float(before or 0)
    except (TypeError, ValueError):
        return None
    if before == 0:
        return None
    return round((now - before) / before * 100)
