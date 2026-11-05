"""
When a branch is open: Sundays, declared holidays, and the hours between.
Fixed dates throughout, so no test depends on the day it runs:
Sat 7, Sun 8, Mon 9, Tue 10 November 2026.
"""
from datetime import date, datetime
from apps.organization.models import Branch
from django.test import TestCase
from django.utils import timezone

from apps.communications.tests import make_org, make_user
from apps.finance.models import PublicHoliday
from apps.organization.services import hours

SAT, SUN, MON, TUE = date(2026, 11, 7), date(2026, 11, 8), date(2026, 11, 9), date(2026, 11, 10)


def at(day, hh, mm=0):
    return timezone.make_aware(datetime(day.year, day.month, day.day, hh, mm))


class HoursTests(TestCase):

    def setUp(self):
        self.branch = make_org()  # opens 08:00, closes 19:30 (the Branch defaults)
        self.manager = make_user('bm@hours.test', self.branch)

    def declare(self, day, name='Farmers Day', branch=None):
        return PublicHoliday.objects.create(
            branch=branch or self.branch, date=day, name=name, declared_by=self.manager,
        )

    # ── Which days ──────────────────────────────────────────────

    def test_sunday_is_closed(self):
        self.assertFalse(hours.is_trading_day(self.branch, SUN))
        self.assertEqual(hours.closed_because(self.branch, SUN), 'Sunday')

    def test_a_weekday_trades(self):
        self.assertTrue(hours.is_trading_day(self.branch, MON))
        self.assertIsNone(hours.closed_because(self.branch, MON))

    def test_a_declared_holiday_closes_that_branch_only(self):
        # make_org can't run twice (Belt.code is unique and left blank), so the
        # second branch shares the first one's region, as the inbox tests do.
        other = Branch.objects.create(name='Other', code='OTH', region=self.branch.region)
        self.declare(MON)
        self.assertFalse(hours.is_trading_day(self.branch, MON))
        self.assertEqual(hours.closed_because(self.branch, MON), 'Farmers Day')
        self.assertTrue(hours.is_trading_day(other, MON))

    def test_next_trading_day_skips_sunday_and_a_holiday(self):
        self.assertEqual(hours.next_trading_day(self.branch, SAT), MON)
        self.declare(MON)
        self.assertEqual(hours.next_trading_day(self.branch, SAT), TUE)

    # ── Which hours ─────────────────────────────────────────────

    def test_open_between_opening_and_closing(self):
        self.assertTrue(hours.is_open(self.branch, at(MON, 10)))
        self.assertFalse(hours.is_open(self.branch, at(MON, 7, 59)))
        self.assertFalse(hours.is_open(self.branch, at(MON, 19, 30)))  # closing time itself is closed

    def test_closed_all_day_on_a_holiday(self):
        self.declare(MON)
        self.assertFalse(hours.is_open(self.branch, at(MON, 10)))

    # ── When next ───────────────────────────────────────────────

    def test_early_morning_opens_later_today(self):
        self.assertEqual(hours.next_opening(self.branch, at(MON, 6)), at(MON, 8))

    def test_saturday_night_opens_monday(self):
        self.assertEqual(hours.next_opening(self.branch, at(SAT, 20)), at(MON, 8))

    def test_a_holiday_monday_pushes_opening_to_tuesday(self):
        self.declare(MON)
        self.assertEqual(hours.next_opening(self.branch, at(SAT, 20)), at(TUE, 8))