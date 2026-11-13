"""
The job page's file (13 Nov 2026): the words the history uses.
"""
from django.test import SimpleTestCase

from apps.jobs.services.job_file import humanise, payment_label, phrase


class JobFileWordsTests(SimpleTestCase):
    def test_known_moves_have_plain_words(self):
        self.assertEqual(phrase('WORK', 'IN_PRODUCTION'), 'Sent to production')
        self.assertEqual(phrase('PAYMENT', 'SETTLED'), 'Paid in full')
        self.assertEqual(phrase('HANDOVER', 'HANDED_OVER'), 'Handed over')

    def test_an_unknown_move_is_still_readable(self):
        self.assertEqual(phrase('WORK', 'LAMINATING_NOW'), 'Laminating now')
        self.assertEqual(phrase('RECORD', 'ANYTHING'), 'Record updated')
        self.assertEqual(humanise(None), '')

    def test_payments_are_named_deposit_then_balance(self):
        self.assertEqual(payment_label(0, 1, True), 'Paid in full')
        self.assertEqual(payment_label(0, 1, False), 'Payment')
        self.assertEqual([payment_label(i, 2, True) for i in range(2)], ['Deposit', 'Balance'])
        self.assertEqual([payment_label(i, 3, True) for i in range(3)], ['Deposit', 'Part payment', 'Balance'])
