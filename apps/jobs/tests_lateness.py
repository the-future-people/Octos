"""Lateness: every rule of when a promise moves and who is told."""

from datetime import datetime, timedelta, timezone as tz

from django.test import SimpleTestCase

from apps.jobs.services.lateness import (
    AT_RISK, BROKEN, KEPT, LATE, ON_TRACK, decide, outcome, round_up_5,
)

T = datetime(2026, 10, 21, 15, 40, tzinfo=tz.utc)      # the promise: 3:40 pm
NOON = datetime(2026, 10, 21, 12, 0, tzinfo=tz.utc)


def m(n):
    return timedelta(minutes=n)


class DecideTests(SimpleTestCase):

    def test_on_time_is_left_alone(self):
        d = decide(promise=T, live=T - m(20), now=NOON, state=ON_TRACK, last_told=None)
        self.assertEqual((d.state, d.new_promise, d.tell_staff, d.tell_customer), (ON_TRACK, None, False, False))

    def test_a_small_wobble_is_not_an_alarm(self):
        d = decide(promise=T, live=T + m(10), now=NOON, state=ON_TRACK, last_told=None)
        self.assertEqual((d.state, d.new_promise), (ON_TRACK, None))

    def test_slipping_fifteen_minutes_moves_the_promise_and_tells_everyone(self):
        d = decide(promise=T, live=T + m(42), now=NOON, state=ON_TRACK, last_told=None)
        self.assertEqual(d.state, AT_RISK)
        self.assertEqual(d.new_promise, datetime(2026, 10, 21, 16, 25, tzinfo=tz.utc))
        self.assertTrue(d.tell_staff and d.tell_customer)

    def test_the_customer_is_not_told_twice_within_two_hours(self):
        d = decide(promise=T, live=T + m(42), now=NOON, state=AT_RISK, last_told=NOON - m(30))
        self.assertTrue(d.tell_staff)
        self.assertFalse(d.tell_customer)

    def test_but_reaching_late_is_always_told(self):
        d = decide(promise=T, live=T + m(42), now=T + m(5), state=AT_RISK, last_told=T - m(10))
        self.assertEqual(d.state, LATE)
        self.assertTrue(d.tell_customer)

    def test_past_the_promise_with_nothing_better_to_say(self):
        d = decide(promise=T, live=None, now=T + m(1), state=ON_TRACK, last_told=None)
        self.assertEqual((d.state, d.tell_staff, d.tell_customer), (LATE, True, True))

    def test_late_is_said_once(self):
        d = decide(promise=T, live=None, now=T + m(30), state=LATE, last_told=T)
        self.assertEqual((d.state, d.tell_staff, d.tell_customer), (LATE, False, False))

    def test_catching_up_is_quiet_and_never_earlier(self):
        d = decide(promise=T, live=T - m(30), now=NOON, state=AT_RISK, last_told=NOON)
        self.assertEqual((d.state, d.new_promise, d.tell_customer), (ON_TRACK, None, False))


class OutcomeTests(SimpleTestCase):

    def test_kept_against_the_first_promise(self):
        self.assertEqual(outcome(first_promise=T, ready_at=T - m(1)), KEPT)
        self.assertEqual(outcome(first_promise=T, ready_at=T), KEPT)

    def test_broken_even_if_a_later_promise_was_met(self):
        self.assertEqual(outcome(first_promise=T, ready_at=T + m(1)), BROKEN)


class RoundingTests(SimpleTestCase):

    def test_up_to_the_next_five_minutes(self):
        self.assertEqual(round_up_5(datetime(2026, 1, 1, 15, 41, tzinfo=tz.utc)).minute, 45)
        self.assertEqual(round_up_5(datetime(2026, 1, 1, 15, 40, tzinfo=tz.utc)).minute, 40)
        self.assertEqual(round_up_5(datetime(2026, 1, 1, 15, 40, 30, tzinfo=tz.utc)).minute, 45)