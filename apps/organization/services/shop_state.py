"""
Is the shop open? One answer for all of Octos (11 Nov 2026).

    OPEN     within opening hours (the calendar: organization/services/hours)
    CLOSING  past closing time, within CLOSING_LIMIT, and a cashier has not yet
             signed off: the doors are shut but the team is still in
    CLOSED   otherwise: every cashier signed off, or long past closing

The shop's own ritual decides when the day is over: the cashier counts the
cash and signs off (finance CashierFloat), then the BM closes the sheet. Until
a cashier signs off, the counter is alive, whatever the timetable says.
CLOSING_LIMIT is the safety net for a cashier who forgets to sign off.

The counter rules, the branch_hours tool and the holding reply all ask here,
so there is one rule in one place.
"""
from datetime import datetime, timedelta

from django.utils import timezone

OPEN, CLOSING, CLOSED = 'OPEN', 'CLOSING', 'CLOSED'
CLOSING_LIMIT = timedelta(hours=3)
SORT_WITHIN = timedelta(minutes=30)      # "we could get it sorted before 8:00"


def cashier_on_post(branch, now=None):
    """Today's open sheet at this branch has a float that is not signed off."""
    from apps.finance.models import CashierFloat
    today = timezone.localtime(now or timezone.now()).date()
    return CashierFloat.objects.filter(
        daily_sheet__branch=branch, daily_sheet__closed_at__isnull=True,
        daily_sheet__created_at__date=today, is_signed_off=False,
    ).exists()


def closing_time(branch, now=None):
    """Today's closing time at this branch, or None on a closed day."""
    from apps.organization.services import hours
    local = timezone.localtime(now or timezone.now())
    try:
        closes = hours.hours_on(branch, local.date())[1]
    except Exception:
        return None
    if not closes:
        return None
    return timezone.make_aware(datetime.combine(local.date(), closes))


def state(branch, now=None):
    from apps.organization.services import hours
    now = now or timezone.now()
    if hours.is_open(branch, now):
        return OPEN
    closing = closing_time(branch, now)
    if closing and closing <= now <= closing + CLOSING_LIMIT and cashier_on_post(branch, now):
        return CLOSING
    return CLOSED


def sort_by(branch, now=None):
    """While closing up: the time the team could still sort a quick job by."""
    closing = closing_time(branch, now)
    return closing + SORT_WITHIN if closing else None


def any_branch(now=None):
    """The best state across the branches Octos speaks for: OPEN, then CLOSING, then CLOSED."""
    from apps.organization.models import Branch
    states = {state(b, now) for b in Branch.objects.filter(is_trading=True, is_active=True)}
    return OPEN if OPEN in states else CLOSING if CLOSING in states else CLOSED
