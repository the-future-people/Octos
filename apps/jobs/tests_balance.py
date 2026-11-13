"""
Taking the balance on a deposit-paid job (13 Nov 2026): the checks.
"""
from decimal import Decimal

from django.test import SimpleTestCase

from apps.jobs.services.balance_service import check_balance_request


class BalanceCheckTests(SimpleTestCase):
    def test_a_deposit_paid_job_returns_its_balance(self):
        self.assertEqual(check_balance_request('DEPOSIT_PAID', '9.00', 'CASH'), Decimal('9.00'))

    def test_a_settled_job_is_refused(self):
        with self.assertRaisesMessage(ValueError, 'already fully paid'):
            check_balance_request('SETTLED', '0', 'CASH')

    def test_an_unpaid_job_goes_through_the_queue_not_here(self):
        with self.assertRaisesMessage(ValueError, 'Take its payment from the queue'):
            check_balance_request('UNPAID', '20.00', 'CASH')

    def test_nothing_owed_is_refused(self):
        with self.assertRaisesMessage(ValueError, 'Nothing is owed'):
            check_balance_request('DEPOSIT_PAID', '0.00', 'CASH')

    def test_credit_is_not_a_way_to_take_a_balance(self):
        with self.assertRaises(ValueError):
            check_balance_request('DEPOSIT_PAID', '9.00', 'CREDIT')

    def test_split_parts_must_add_up_to_the_balance(self):
        legs = [{'method': 'MOMO', 'amount': '20.00'}, {'method': 'CASH', 'amount': '22.90'}]
        self.assertEqual(check_balance_request('DEPOSIT_PAID', '42.90', 'SPLIT', legs), Decimal('42.90'))
        with self.assertRaisesMessage(ValueError, 'must add up'):
            check_balance_request('DEPOSIT_PAID', '58.35', 'SPLIT', legs)
