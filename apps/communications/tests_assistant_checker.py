"""
The checker: no price, time or job reference reaches a customer unless
the tools returned it in the same run.
"""
from django.test import SimpleTestCase

from apps.communications.assistant.checker import unverified

FACTS = (
    '{"total": "GHS 30.00", "unit_price": "GHS 2.50"} '
    '{"today": {"opens": "8:00am", "closes": "7:30pm"}, "next_opening": "8:00am tomorrow"} '
    '{"ref": "5629", "balance_due": "GHS 120.00"}'
)


class CheckerTests(SimpleTestCase):

    def test_a_reply_with_no_figures_passes(self):
        self.assertEqual(unverified('Good evening 👋 Octos here. How can I help?', FACTS), [])

    def test_figures_from_the_tools_pass_however_they_are_written(self):
        reply = ('That comes to GHS 30, or 30 cedis if you prefer 😊 We open at 8am and close '
                 'at 7:30 pm. Your order ref 5629 has GH₵120.00 left to pay.')
        self.assertEqual(unverified(reply, FACTS), [])

    def test_a_price_the_tools_never_gave_is_caught(self):
        self.assertEqual(unverified('That comes to GHS 35.', FACTS), ['GHS 35.00'])

    def test_a_made_up_time_is_caught(self):
        self.assertEqual(unverified('It will be ready by 4pm today.', FACTS), ['4:00pm'])

    def test_a_job_reference_the_tools_never_gave_is_caught(self):
        self.assertEqual(unverified('Your order ref 912 is ready.', FACTS), ['ref 912'])

    def test_quantities_and_sizes_are_not_mistaken_for_prices(self):
        self.assertEqual(unverified('300 stickers at 2.5 inches, A3, 5 sets.', FACTS), [])

    def test_several_problems_are_all_reported(self):
        self.assertEqual(
            unverified('GHS 40 for this, ready at 3pm.', FACTS),
            ['GHS 40.00', '3:00pm'],
        )