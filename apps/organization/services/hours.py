"""
When a branch is open: the one place everything asks.

A branch trades Monday to Saturday, from its opening_time to its
closing_time, except on a public holiday its manager has declared.
Saturday may have hours of its own (saturday_opening_time and
saturday_closing_time; empty means the same as weekdays): Westland opens
9:00am to 5:30pm on Saturdays (7 Nov 2026).

Until November 2026 this was known in pieces: "Sunday is closed" written
out by hand in finance views, declared holidays read only by finance, and
the promise engine skipping Sundays but not holidays, so it could promise
work for a day the doors were shut. Octos's assistant, the promise engine
and anything else that needs to know asks here, so they can't disagree.
"""
from datetime import datetime, timedelta

from django.utils import timezone

SATURDAY = 5
SUNDAY = 6


def hours_on(branch, day):
    """(opening, closing) times on this date: Saturday's own when the branch has them."""
    if (day.weekday() == SATURDAY and getattr(branch, 'saturday_opening_time', None)
            and getattr(branch, 'saturday_closing_time', None)):
        return branch.saturday_opening_time, branch.saturday_closing_time
    return branch.opening_time, branch.closing_time


def is_trading_day(branch, day):
    """Open at all on this date: not a Sunday, and no holiday declared."""
    if day.weekday() == SUNDAY:
        return False
    from apps.finance.models import PublicHoliday
    return not PublicHoliday.objects.filter(branch=branch, date=day).exists()


def closed_because(branch, day):
    """Why the branch is shut on this date ('Sunday', a holiday's name), or None if it trades."""
    if day.weekday() == SUNDAY:
        return 'Sunday'
    from apps.finance.models import PublicHoliday
    holiday = PublicHoliday.objects.filter(branch=branch, date=day).first()
    return (holiday.name or 'a public holiday') if holiday else None


def next_trading_day(branch, after):
    """The first trading day strictly after the given date."""
    day = after + timedelta(days=1)
    for _ in range(31):
        if is_trading_day(branch, day):
            return day
        day += timedelta(days=1)
    # A month with no trading day is a data error, not a calendar. Stop
    # rather than loop forever; the caller still gets a date.
    return day


def opening_at(branch, day, tz=None):
    return timezone.make_aware(
        datetime.combine(day, hours_on(branch, day)[0]), tz or timezone.get_current_timezone()
    )


def closing_at(branch, day, tz=None):
    return timezone.make_aware(
        datetime.combine(day, hours_on(branch, day)[1]), tz or timezone.get_current_timezone()
    )


def is_open(branch, at=None):
    """Doors open at this moment (now, if not given)."""
    at = timezone.localtime(at or timezone.now())
    opens, closes = hours_on(branch, at.date())
    return is_trading_day(branch, at.date()) and opens <= at.time() < closes


def next_opening(branch, at=None):
    """
    When the doors next open: later today if it's still early on a
    trading day, otherwise the next trading day's opening.
    """
    at = timezone.localtime(at or timezone.now())
    if is_trading_day(branch, at.date()) and at.time() < hours_on(branch, at.date())[0]:
        return opening_at(branch, at.date(), at.tzinfo)
    return opening_at(branch, next_trading_day(branch, at.date()), at.tzinfo)
