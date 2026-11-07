"""
Saturday's own hours, and ready times said as windows (7 Nov 2026).
Westland: Monday to Friday 7:30am to 7:30pm, Saturday 9:00am to 5:30pm.
"""
from datetime import datetime, time

from django.test import TestCase
from django.utils import timezone

from apps.communications.tests import make_org
from apps.organization.services import hours


def at(y, m, d, hh, mm=0):
    return timezone.make_aware(datetime(y, m, d, hh, mm))


class SaturdayHoursTests(TestCase):

    def setUp(self):
        self.branch = make_org()
        self.branch.opening_time, self.branch.closing_time = time(7, 30), time(19, 30)
        self.branch.saturday_opening_time, self.branch.saturday_closing_time = time(9, 0), time(17, 30)
        self.branch.save()

    def test_saturday_keeps_its_own_hours(self):
        # 7 Nov 2026 is a Saturday.
        self.assertFalse(hours.is_open(self.branch, at(2026, 11, 7, 8, 30)))
        self.assertTrue(hours.is_open(self.branch, at(2026, 11, 7, 9, 15)))
        self.assertFalse(hours.is_open(self.branch, at(2026, 11, 7, 18, 0)))

    def test_weekdays_keep_theirs(self):
        self.assertTrue(hours.is_open(self.branch, at(2026, 11, 6, 7, 45)))
        self.assertTrue(hours.is_open(self.branch, at(2026, 11, 6, 19, 0)))

    def test_after_friday_it_next_opens_on_saturday_morning_at_nine(self):
        opening = timezone.localtime(hours.next_opening(self.branch, at(2026, 11, 6, 20, 0)))
        self.assertEqual((opening.day, opening.hour, opening.minute), (7, 9, 0))

    def test_saturday_closes_at_half_past_five(self):
        closing = timezone.localtime(hours.closing_at(self.branch, at(2026, 11, 7, 10).date()))
        self.assertEqual((closing.hour, closing.minute), (17, 30))

    def test_with_no_saturday_hours_saturday_is_a_weekday(self):
        self.branch.saturday_opening_time = self.branch.saturday_closing_time = None
        self.branch.save()
        self.assertTrue(hours.is_open(self.branch, at(2026, 11, 7, 7, 45)))


class ReadyWindowTests(TestCase):

    def test_rounded_up_to_the_quarter_then_half_an_hour(self):
        from apps.communications.assistant.tools import _window
        now = at(2026, 11, 7, 14, 0)
        self.assertEqual(_window(at(2026, 11, 7, 18, 17), now), 'between 6:30pm and 7:00pm today')
        self.assertEqual(_window(at(2026, 11, 7, 17, 30), now), 'between 5:30pm and 6:00pm today')
        self.assertEqual(_window(at(2026, 11, 9, 9, 5), now), 'between 9:15am and 9:45am on Monday')
