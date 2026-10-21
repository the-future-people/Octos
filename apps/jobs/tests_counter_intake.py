"""The 70% rule for floor work taken at the counter."""

from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.jobs.services.counter_intake import has_paid_enough, minimum_due


def job(cost, paid, method='CASH'):
    return SimpleNamespace(estimated_cost=Decimal(cost), amount_paid=Decimal(paid), payment_method=method)


class MinimumTests(SimpleTestCase):

    def test_the_minimum_is_seventy_percent(self):
        self.assertEqual(minimum_due(job('120.00', '0')), Decimal('84.00'))

    def test_seventy_percent_is_enough(self):
        self.assertTrue(has_paid_enough(job('120.00', '84.00')))

    def test_less_is_not(self):
        self.assertFalse(has_paid_enough(job('120.00', '83.99')))

    def test_paid_in_full_is_enough(self):
        self.assertTrue(has_paid_enough(job('120.00', '120.00')))

    def test_a_credit_account_needs_nothing_up_front(self):
        self.assertTrue(has_paid_enough(job('120.00', '0', method='CREDIT')))

    def test_no_cost_means_not_yet(self):
        self.assertFalse(has_paid_enough(job('0', '0')))