"""
The promise engine and declared public holidays.

Until November 2026 PredictionService skipped Sundays only, so a ready
time could land on a holiday the branch manager had declared closed. It
now asks the one calendar (organization/services/hours).
Fixed dates: Sat 7, Mon 9, Tue 10 November 2026.
"""
from datetime import date, datetime
from django.test import TestCase
from django.utils import timezone

from apps.communications.tests import make_org, make_user
from apps.finance.models import PublicHoliday
from apps.production.services.prediction_service import PredictionService

SAT, MON, TUE = date(2026, 11, 7), date(2026, 11, 9), date(2026, 11, 10)


def at(day, hh, mm=0):
    return timezone.make_aware(datetime(day.year, day.month, day.day, hh, mm))


class PromiseHolidayTests(TestCase):

    def setUp(self):
        self.branch = make_org()  # 08:00 to 19:30
        self.engine = PredictionService(self.branch)

    def declare_monday(self):
        PublicHoliday.objects.create(
            branch=self.branch, date=MON, name='Farmers Day',
            declared_by=make_user('bm@promise.test', self.branch),
        )

    def test_saturday_night_starts_monday(self):
        self.assertEqual(self.engine._next_working_moment(at(SAT, 20)), at(MON, 8))

    def test_a_holiday_monday_starts_tuesday(self):
        self.declare_monday()
        self.assertEqual(self.engine._next_working_moment(at(SAT, 20)), at(TUE, 8))

    def test_work_arriving_on_the_holiday_itself_waits(self):
        self.declare_monday()
        self.assertEqual(self.engine._next_working_moment(at(MON, 10)), at(TUE, 8))

    def test_work_carrying_over_skips_the_holiday(self):
        # An hour of work starting at 19:00 Saturday: 30 minutes before
        # closing, the other 30 at the next opening.
        self.declare_monday()
        self.assertEqual(self.engine._add_working_minutes(at(SAT, 19), 60), at(TUE, 8, 30))

    
    def test_no_work_is_ready_at_once_and_warns_nothing(self):
        with self.assertNoLogs('apps.production.services.prediction_service', level='WARNING'):
            self.assertEqual(self.engine._add_working_minutes(at(MON, 10), 0), at(MON, 10))