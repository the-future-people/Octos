from decimal import Decimal

from django.test import TestCase

from apps.analytics.engines.prediction_engine import PredictionEngine
from apps.customers.models import CustomerProfile
from apps.finance.credit_engine import CreditEngine
from apps.finance.models import CreditAccount, CreditPayment
from apps.jobs.tests import JobsFixtureMixin


class CreditSignalDoubleCountTests(JobsFixtureMixin, TestCase):
    """
    CreditEngine.settle() lowers current_balance the moment a payment is
    taken. The prediction engine reads current_balance as what is still
    owed, so today's settlements are already out of it and must not be
    subtracted a second time.
    """

    HOUR = 10.0  # mid-morning: the time factor is at its maximum

    def _account(self, phone, balance):
        customer = CustomerProfile.objects.create(
            phone=phone, affiliation_active=True,
            customer_type=CustomerProfile.INDIVIDUAL,
            visit_count=0, total_spend=Decimal('0'),
            tier=CustomerProfile.REGULAR, confidence_score=0,
            is_priority=False, is_walkin=False,
            first_name='Credit', last_name=phone[-3:],
        )
        return CreditAccount.objects.create(
            customer=customer,
            branch=self.branch,
            account_type=CreditAccount.AccountType.INDIVIDUAL,
            status=CreditAccount.Status.ACTIVE,
            credit_limit=Decimal('2000.00'),
            current_balance=balance,
            payment_terms=30,
        )

    def _settle(self, account, amount):
        CreditEngine(account).settle(
            amount=amount,
            payment_method=CreditPayment.PaymentMethod.CASH,
            actor=self.cashier,
            daily_sheet=self.sheet,
        )

    def _signal(self):
        result = PredictionEngine(self.branch)._credit_signal(None, self.HOUR)
        self.assertIn(
            'p_settle', result,
            f'Credit signal returned early or failed: {result}',
        )
        return result

    def _assert_contribution_uses(self, result, owed):
        """The contribution must be built on what is actually still owed."""
        expected = owed * result['p_settle'] * result['weight']
        self.assertAlmostEqual(result['contribution'], expected, places=2)

    def test_partial_settlement_is_not_subtracted_twice(self):
        account = self._account('0555100001', Decimal('1000.00'))
        self._settle(account, Decimal('400.00'))

        result = self._signal()

        self.assertEqual(result['outstanding'], 600.0)
        self.assertEqual(result['settled_today'], 400.0)
        self._assert_contribution_uses(result, 600.0)

    def test_full_settlement_does_not_reduce_other_accounts(self):
        paid_off = self._account('0555100002', Decimal('300.00'))
        self._account('0555100003', Decimal('500.00'))
        self._settle(paid_off, Decimal('300.00'))

        result = self._signal()

        self.assertEqual(result['outstanding'], 500.0)
        self._assert_contribution_uses(result, 500.0)