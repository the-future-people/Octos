"""
Customer reminders (13 Nov 2026): when each is due, and what it says.
"""
from django.test import SimpleTestCase

from apps.jobs.services.reminders import feedback_texts, pickup_step, pickup_texts


class PickupStepTests(SimpleTestCase):
    def test_nothing_before_two_days(self):
        self.assertIsNone(pickup_step(1, set()))

    def test_day_two_then_day_seven_then_nothing(self):
        self.assertEqual(pickup_step(2, set()), 'day2')
        self.assertIsNone(pickup_step(3, {'day2'}))
        self.assertEqual(pickup_step(7, {'day2'}), 'day7')
        self.assertIsNone(pickup_step(8, {'day2', 'day7'}))

    def test_never_more_than_twice_even_if_day_two_was_missed(self):
        self.assertEqual(pickup_step(8, set()), 'day7')
        self.assertIsNone(pickup_step(9, {'day7'}))

    def test_an_old_backlog_is_not_messaged(self):
        self.assertIsNone(pickup_step(11, set()))


class TextTests(SimpleTestCase):
    def test_the_balance_is_mentioned_when_owed(self):
        wa, sms = pickup_texts('Faustina', 'A4 Colour Printing', 'day2', 'Thursday 13 November', 9)
        self.assertIn('GHS 9.00 left to pay', wa)
        self.assertIn('63 Westlands Ave', sms)

    def test_no_balance_line_when_paid(self):
        wa, _ = pickup_texts('Faustina', 'Flexy Banner', 'day7', 'Thursday 13 November', 0)
        self.assertNotIn('left to pay', wa)
        self.assertIn('ready since Thursday 13 November', wa)

    def test_feedback_sms_points_to_whatsapp(self):
        _, sms = feedback_texts('')
        self.assertTrue(sms.startswith('Hello'))
        self.assertIn('055 196 9777', sms)
