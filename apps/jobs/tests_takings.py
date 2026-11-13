"""
Money taken comes from receipts (13 Nov 2026): the arithmetic that adds them up.
"""
from decimal import Decimal

from django.test import SimpleTestCase

from apps.jobs.selectors.revenue_selectors import add_rows


def empty():
    return {c: {'total': Decimal('0'), 'count': 0} for c in ('CASH', 'MOMO', 'POS')}


class TakingsTests(SimpleTestCase):
    def test_receipts_add_up_by_method(self):
        out = add_rows(empty(), [{'payment_method': 'CASH', 't': Decimal('227.50'), 'n': 16},
                                 {'payment_method': 'MOMO', 't': Decimal('129.67'), 'n': 4}], 't')
        self.assertEqual(out['CASH'], {'total': Decimal('227.50'), 'count': 16})
        self.assertEqual(out['MOMO']['total'], Decimal('129.67'))

    def test_a_split_adds_each_leg_to_its_own_method(self):
        out = add_rows(empty(), [{'payment_method': 'CASH', 't': Decimal('227.50'), 'n': 16}], 't')
        add_rows(out, [{'payment_method': 'CASH', 't': Decimal('3.00'), 'n': 1},
                       {'payment_method': 'MOMO', 't': Decimal('2.00'), 'n': 1}], 't')
        self.assertEqual(out['CASH']['total'], Decimal('230.50'))
        self.assertEqual(out['MOMO']['total'], Decimal('2.00'))

    def test_methods_that_are_not_money_in_are_left_out(self):
        out = add_rows(empty(), [{'payment_method': 'CREDIT', 't': Decimal('80.00'), 'n': 1},
                                 {'payment_method': 'WALLET', 't': Decimal('20.00'), 'n': 1}], 't')
        self.assertEqual(sum(v['total'] for v in out.values()), Decimal('0'))
