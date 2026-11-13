"""
A cashier's own numbers, each checked on its own (12 Nov 2026).
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase

from apps.finance.services.my_numbers import accuracy, busiest, by_method, wait_to_pay, whatsapp

T = datetime(2026, 11, 12, 10, 0, tzinfo=dt_timezone.utc)


class MyNumbersTests(SimpleTestCase):
    def test_accuracy_counts_exact_sign_offs(self):
        out = accuracy([('2026-11-12', '0.00'), ('2026-11-11', '-2.00'), ('2026-11-10', '0.01')])
        self.assertEqual((out['exact'], out['of']), (2, 3))
        self.assertFalse(out['shifts'][1]['exact'])

    def test_wait_to_pay_is_the_average_in_minutes(self):
        self.assertEqual(wait_to_pay([(T, T + timedelta(minutes=4)), (T, T + timedelta(minutes=8))]), 6)
        self.assertIsNone(wait_to_pay([]))

    def test_busiest_hour(self):
        times = [T, T + timedelta(minutes=10), T + timedelta(hours=2)]
        out = busiest(times)
        self.assertEqual(out['peak_count'], 2)
        self.assertEqual(sum(h['count'] for h in out['by_hour']), 3)

    def test_whatsapp_counts_chat_customers(self):
        out = whatsapp([(True, True), (False, True), (True, False), (False, False)])
        self.assertEqual(out, {'sent': 2, 'of': 4, 'chat_customers': 2, 'chat_sent': 1})

    def test_takings_by_method(self):
        out = by_method([('CASH', '20.00'), ('CASH', '5.00'), ('MOMO', '52.00')])
        self.assertEqual(out['methods']['CASH'], {'amount': '25.00', 'count': 2})
        self.assertEqual((out['total'], out['count']), ('77.00', 3))
