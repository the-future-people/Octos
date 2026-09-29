"""
Stranded sheet recovery tests.

A sheet that is never closed on its own day strands every day after it,
because the next day's float is only staged during close. These tests
cover the service that unwinds that: the manager's two-day ceiling, the
float staging and linking sequence, variance handling, and the cascade
where closing one day stages the next.

Fixtures are built from scratch — Django's TestCase runs against a fresh
empty database, so nothing here may depend on development or staging data.

Run inside Docker:
    docker compose exec web python manage.py test apps.finance.tests
"""

import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser, Role
from apps.finance.models import CashierFloat, DailySalesSheet, Receipt
from apps.finance.services.recovery_service import RecoveryService
from apps.organization.models import Branch


class RecoveryFixtureMixin:
    """A branch, a manager, a cashier, and helpers to build past days."""

    @classmethod
    def setUpTestData(cls):
        cls.bm_role = Role.objects.create(
            name='BRANCH_MANAGER', display_name='Branch Manager',
            is_constrained=False, scope='BRANCH',
        )
        cls.cashier_role = Role.objects.create(
            name='CASHIER', display_name='Cashier',
            is_constrained=False, scope='BRANCH',
        )

        cls.branch = Branch.objects.create(
            name='Recovery Test Branch', code='RTB',
            is_headquarters=False, is_regional_hq=False,
            address='1 Test Road',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30),
            closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )

        cls.bm = CustomUser(
            employee_id='RTB-BM-001',
            first_name='Test', last_name='Manager',
            email='bm@recovery.test',
            employment_status='ACTIVE', is_active=True,
            branch=cls.branch, role=cls.bm_role,
        )
        cls.bm.set_password('test-pass-123')
        cls.bm.save()

        cls.cashier = CustomUser(
            employee_id='RTB-CSH-001',
            first_name='Test', last_name='Cashier',
            email='cashier@recovery.test',
            employment_status='ACTIVE', is_active=True,
            branch=cls.branch, role=cls.cashier_role,
        )
        cls.cashier.set_password('test-pass-123')
        cls.cashier.save()

    def make_sheet(self, days_ago, status=DailySalesSheet.Status.OPEN):
        """
        A sheet dated some number of *trading* days before today.

        Counting calendar days and then stepping back off Sunday made two
        different days_ago values collide: on a Monday, days_ago=2 is
        Saturday and days_ago=3 is Sunday, which steps back onto the same
        Saturday. Same branch, same date, unique constraint. It only
        failed on Mondays, which is why it sat here unnoticed.
        """
        d = timezone.localdate()
        remaining = days_ago
        while remaining > 0:
            d -= datetime.timedelta(days=1)
            if d.weekday() != 6:   # the branch never trades on Sunday
                remaining -= 1
        return DailySalesSheet.objects.create(
            branch=self.branch, date=d, status=status,
        )

    def add_cash_receipt(self, sheet, amount, seq=1):
        """A non-void cash receipt, which is what expected_cash is built from."""
        return Receipt.objects.create(
            daily_sheet=sheet,
            cashier=self.cashier,
            receipt_number=f'RTB-{sheet.date:%Y%m%d}-{seq:04d}',
            sequence=seq,
            receipt_type='JOB_PAYMENT',
            payment_method='CASH',
            amount_paid=Decimal(str(amount)),
            balance_due=Decimal('0.00'),
            subtotal=Decimal(str(amount)),
            vat_rate=Decimal('0'), vat_amount=Decimal('0'),
            nhil_amount=Decimal('0'), getfund_amount=Decimal('0'),
            is_void=False,
        )


class StrandedSheetDetectionTests(RecoveryFixtureMixin, TestCase):
    """What counts as stranded, and when the manager is allowed to act."""

    def test_open_past_sheet_is_stranded(self):
        sheet = self.make_sheet(days_ago=2)
        stranded = RecoveryService.get_stranded_sheets(self.branch)
        self.assertIn(sheet, stranded)

    def test_todays_sheet_is_not_stranded(self):
        today = DailySalesSheet.objects.create(
            branch=self.branch,
            date=timezone.localdate(),
            status=DailySalesSheet.Status.OPEN,
        )
        stranded = RecoveryService.get_stranded_sheets(self.branch)
        self.assertNotIn(today, stranded)

    def test_closed_sheet_is_not_stranded(self):
        sheet = self.make_sheet(days_ago=3, status=DailySalesSheet.Status.CLOSED)
        stranded = RecoveryService.get_stranded_sheets(self.branch)
        self.assertNotIn(sheet, stranded)

    def test_stranded_sheets_are_oldest_first(self):
        newer = self.make_sheet(days_ago=2)
        older = self.make_sheet(days_ago=5)
        stranded = RecoveryService.get_stranded_sheets(self.branch)
        self.assertLess(
            stranded.index(older), stranded.index(newer),
            'Recovery must proceed oldest first, since each close stages the next day.',
        )

    def test_manager_may_recover_within_ceiling(self):
        self.make_sheet(days_ago=2)
        self.make_sheet(days_ago=3)
        gate = RecoveryService.can_recover(self.branch)
        self.assertTrue(gate['allowed'])
        self.assertFalse(gate['requires_rm'])
        self.assertEqual(gate['stranded_count'], 2)

    def test_manager_is_blocked_past_ceiling(self):
        self.make_sheet(days_ago=2)
        self.make_sheet(days_ago=3)
        self.make_sheet(days_ago=4)
        gate = RecoveryService.can_recover(self.branch)
        self.assertFalse(gate['allowed'])
        self.assertTrue(gate['requires_rm'])
        self.assertEqual(gate['stranded_count'], 3)

    def test_regional_manager_is_not_bound_by_the_ceiling(self):
        """
        The ceiling escalates to an RM, so it cannot also bind them —
        otherwise a backlog past the limit could not be cleared by anyone.
        """
        rm_role = Role.objects.create(
            name='REGIONAL_MANAGER', display_name='Regional Manager',
            is_constrained=False, scope='REGION',
        )
        rm = CustomUser(
            employee_id='RTB-RM-001',
            first_name='Test', last_name='Regional',
            email='rm@recovery.test',
            employment_status='ACTIVE', is_active=True,
            branch=self.branch, role=rm_role,
        )
        rm.set_password('test-pass-123')
        rm.save()

        self.make_sheet(days_ago=2)
        self.make_sheet(days_ago=3)
        self.make_sheet(days_ago=4)

        bm_gate = RecoveryService.can_recover(self.branch, actor=self.bm)
        rm_gate = RecoveryService.can_recover(self.branch, actor=rm)

        self.assertTrue(bm_gate['requires_rm'])
        self.assertFalse(bm_gate['allowed'])
        self.assertFalse(rm_gate['requires_rm'])
        self.assertTrue(rm_gate['allowed'])

    def test_manager_may_recover_within_ceiling_when_actor_given(self):
        self.make_sheet(days_ago=2)
        self.make_sheet(days_ago=3)
        gate = RecoveryService.can_recover(self.branch, actor=self.bm)
        self.assertTrue(gate['allowed'])
        self.assertFalse(gate['requires_rm'])

    def test_nothing_stranded_means_nothing_to_allow(self):
        gate = RecoveryService.can_recover(self.branch)
        self.assertFalse(gate['allowed'])
        self.assertFalse(gate['requires_rm'])
        self.assertEqual(gate['stranded_count'], 0)


class RecoveryContextTests(RecoveryFixtureMixin, TestCase):
    """The figures shown before the manager enters anything."""

    def test_expected_cash_matches_receipts_plus_float(self):
        sheet = self.make_sheet(days_ago=2)
        self.add_cash_receipt(sheet, '150.00', seq=1)
        self.add_cash_receipt(sheet, '75.50', seq=2)

        ctx = RecoveryService.get_recovery_context(sheet)

        self.assertEqual(ctx['cash_collected'], Decimal('225.50'))
        self.assertEqual(
            ctx['expected_cash'],
            ctx['suggested_opening'] + Decimal('225.50'),
        )

    def test_void_receipts_are_excluded(self):
        sheet = self.make_sheet(days_ago=2)
        self.add_cash_receipt(sheet, '100.00', seq=1)
        voided = self.add_cash_receipt(sheet, '999.00', seq=2)
        voided.is_void = True
        voided.save(update_fields=['is_void'])

        ctx = RecoveryService.get_recovery_context(sheet)
        self.assertEqual(ctx['cash_collected'], Decimal('100.00'))

    def test_context_reports_missing_float(self):
        sheet = self.make_sheet(days_ago=2)
        ctx = RecoveryService.get_recovery_context(sheet)
        self.assertFalse(ctx['has_float'])
        self.assertIsNone(ctx['float_id'])
        self.assertEqual(ctx['cashier_id'], self.cashier.pk)


class RecoverSheetTests(RecoveryFixtureMixin, TestCase):
    """The recovery itself."""

    def _recover(self, sheet, closing_cash, **overrides):
        kwargs = dict(
            sheet           = sheet,
            opening_float   = Decimal('100.00'),
            closing_cash    = Decimal(str(closing_cash)),
            reason          = DailySalesSheet.RecoveryReason.POWER_OUTAGE,
            notes           = 'City-wide outage ended the shift early.',
            recovered_by    = self.bm,
            reconciled_with = self.cashier,
        )
        kwargs.update(overrides)
        return RecoveryService.recover_sheet(**kwargs)

    def test_recovery_closes_the_sheet(self):
        sheet = self.make_sheet(days_ago=2)
        self.add_cash_receipt(sheet, '200.00')

        result = self._recover(sheet, '300.00')

        self.assertTrue(result['ok'], result.get('error'))
        sheet.refresh_from_db()
        self.assertIn(
            sheet.status,
            [DailySalesSheet.Status.CLOSED, DailySalesSheet.Status.AUTO_CLOSED],
        )

    def test_recovery_creates_and_signs_off_a_float(self):
        sheet = self.make_sheet(days_ago=2)
        self.add_cash_receipt(sheet, '200.00')

        self._recover(sheet, '300.00')

        float_record = CashierFloat.objects.get(daily_sheet=sheet)
        self.assertTrue(float_record.is_signed_off)
        self.assertEqual(float_record.closing_cash, Decimal('300.00'))
        self.assertEqual(float_record.opening_float, Decimal('100.00'))

    def test_recovery_entry_is_flagged_and_attributed(self):
        sheet = self.make_sheet(days_ago=2)
        self.add_cash_receipt(sheet, '200.00')

        self._recover(sheet, '300.00')

        float_record = CashierFloat.objects.get(daily_sheet=sheet)
        self.assertTrue(
            float_record.is_recovery_entry,
            'A backdated sign-off must be distinguishable from a real one.',
        )
        self.assertEqual(float_record.reconciled_with, self.cashier)
        self.assertEqual(float_record.signed_off_by, self.bm)

    def test_recovery_records_reason_and_notes_on_sheet(self):
        sheet = self.make_sheet(days_ago=2)
        self.add_cash_receipt(sheet, '200.00')

        self._recover(sheet, '300.00')

        sheet.refresh_from_db()
        self.assertEqual(
            sheet.recovery_reason,
            DailySalesSheet.RecoveryReason.POWER_OUTAGE,
        )
        self.assertEqual(sheet.recovered_by, self.bm)
        self.assertIsNotNone(sheet.recovered_at)
        self.assertTrue(sheet.recovery_notes)

    def test_tallying_count_gives_zero_variance(self):
        sheet = self.make_sheet(days_ago=2)
        self.add_cash_receipt(sheet, '200.00')

        result = self._recover(sheet, '300.00')

        self.assertTrue(result['ok'], result.get('error'))
        self.assertEqual(result['variance'], Decimal('0.00'))

    def test_variance_without_explanation_is_refused(self):
        sheet = self.make_sheet(days_ago=2)
        self.add_cash_receipt(sheet, '200.00')

        result = self._recover(sheet, '250.00')

        self.assertFalse(result['ok'])
        sheet.refresh_from_db()
        self.assertEqual(
            sheet.status, DailySalesSheet.Status.OPEN,
            'A refused recovery must leave the sheet untouched.',
        )

    def test_variance_with_explanation_is_recorded(self):
        sheet = self.make_sheet(days_ago=2)
        self.add_cash_receipt(sheet, '200.00')

        result = self._recover(
            sheet, '250.00',
            variance_notes='GHS 50 shortfall, cashier confirmed at reconciliation.',
        )

        self.assertTrue(result['ok'], result.get('error'))
        self.assertEqual(result['variance'], Decimal('-50.00'))

    def test_empty_notes_are_refused(self):
        sheet = self.make_sheet(days_ago=2)
        result = self._recover(sheet, '100.00', notes='   ')
        self.assertFalse(result['ok'])

    def test_invalid_reason_is_refused(self):
        sheet = self.make_sheet(days_ago=2)
        result = self._recover(sheet, '100.00', reason='DOG_ATE_IT')
        self.assertFalse(result['ok'])

    def test_todays_sheet_cannot_be_recovered(self):
        today = DailySalesSheet.objects.create(
            branch=self.branch,
            date=timezone.localdate(),
            status=DailySalesSheet.Status.OPEN,
        )
        result = self._recover(today, '100.00')
        self.assertFalse(result['ok'])

    def test_closed_sheet_cannot_be_recovered_again(self):
        sheet = self.make_sheet(days_ago=2, status=DailySalesSheet.Status.CLOSED)
        result = self._recover(sheet, '100.00')
        self.assertFalse(result['ok'])

    def test_recovery_blocked_when_backlog_needs_rm(self):
        oldest = self.make_sheet(days_ago=4)
        self.make_sheet(days_ago=3)
        self.make_sheet(days_ago=2)

        result = self._recover(oldest, '100.00')

        self.assertFalse(result['ok'])
        self.assertIn('regional manager', result['error'].lower())

    def test_manager_corrected_opening_float_is_used(self):
        """
        The opening figure feeds expected_cash, so when the manager finds
        the cashier actually started with something else, that must win.
        """
        sheet = self.make_sheet(days_ago=2)
        self.add_cash_receipt(sheet, '200.00')

        result = self._recover(
            sheet, '250.00', opening_float=Decimal('50.00'),
        )

        self.assertTrue(result['ok'], result.get('error'))
        self.assertEqual(result['variance'], Decimal('0.00'))
        float_record = CashierFloat.objects.get(daily_sheet=sheet)
        self.assertEqual(float_record.opening_float, Decimal('50.00'))

class SnapshotTotalsTests(RecoveryFixtureMixin, TestCase):
    """
    _snapshot_totals freezes the day's figures at close. This pins what it
    produces today, so moving it onto the payment registry can be proved to
    change nothing. The last test is the one that matters: a method the
    sorting does not recognise currently lands in no total at all, and the
    money disappears from the books with no error raised.
    """

    def setUp(self):
        self.sheet = self.make_sheet(0)

    def _receipt(self, method, amount, seq):
        return Receipt.objects.create(
            daily_sheet=self.sheet,
            cashier=self.cashier,
            receipt_number=f'RTB-SNAP-{seq:04d}',
            sequence=seq,
            receipt_type='JOB_PAYMENT',
            payment_method=method,
            amount_paid=Decimal(str(amount)),
            balance_due=Decimal('0.00'),
            subtotal=Decimal(str(amount)),
            vat_rate=Decimal('0'), vat_amount=Decimal('0'),
            nhil_amount=Decimal('0'), getfund_amount=Decimal('0'),
            is_void=False,
        )

    def _snapshot(self):
        from apps.finance.sheet_engine import SheetEngine
        SheetEngine(self.branch)._snapshot_totals(self.sheet)
        self.sheet.refresh_from_db()

    def test_totals_are_sorted_by_method(self):
        self._receipt('CASH', '100.00', 1)
        self._receipt('CASH',  '50.00', 2)
        self._receipt('MOMO',  '75.00', 3)
        self._receipt('POS',   '25.00', 4)

        self._snapshot()

        self.assertEqual(self.sheet.total_cash, Decimal('150.00'))
        self.assertEqual(self.sheet.total_momo, Decimal('75.00'))
        self.assertEqual(self.sheet.total_pos,  Decimal('25.00'))

    def test_void_receipts_are_ignored(self):
        self._receipt('CASH', '100.00', 5)
        voided = self._receipt('CASH', '999.00', 6)
        voided.is_void = True
        voided.save(update_fields=['is_void'])

        self._snapshot()

        self.assertEqual(self.sheet.total_cash, Decimal('100.00'))

    def test_credit_receipts_total_as_credit_issued(self):
        self._receipt('CASH',   '100.00', 7)
        self._receipt('CREDIT', '300.00', 8)

        self._snapshot()

        self.assertEqual(self.sheet.total_cash,           Decimal('100.00'))
        self.assertEqual(self.sheet.total_credit_issued,  Decimal('300.00'))

    def test_an_unknown_method_is_reported_not_silently_dropped(self):
        """
        A method the registry does not know still cannot be totalled — it
        has no column to go to. What changed is that it is now named in
        the logs with its sheet and its amount, instead of disappearing.
        """
        self._receipt('CASH',    '100.00', 9)
        self._receipt('CHEQUE',  '250.00', 10)

        with self.assertLogs('apps.finance.sheet_engine', level='ERROR') as logged:
            self._snapshot()

        self.assertIn('CHEQUE', ''.join(logged.output))
        self.assertIn('250.00', ''.join(logged.output))
        self.assertEqual(self.sheet.total_cash, Decimal('100.00'))

    def test_online_money_is_earned_but_never_in_the_till(self):
        """
        Yesterday this same receipt was logged as an unknown method and
        counted nowhere. One registry entry later, it lands in its own
        column, counts as revenue, and still cannot touch the till.
        """
        self._receipt('CASH',   '100.00', 11)
        self._receipt('ONLINE', '250.00', 12)

        self._snapshot()

        self.assertEqual(self.sheet.total_cash,   Decimal('100.00'))
        self.assertEqual(self.sheet.total_online, Decimal('250.00'))
        self.assertEqual(self.sheet.total_collected, Decimal('350.00'))
        # The drawer holds the cash and nothing else.
        self.assertEqual(self.sheet.net_cash_in_till, Decimal('100.00'))

class RevenueBreakdownTests(RecoveryFixtureMixin, TestCase):
    """
    The live figures the cashier and BM read during the day. Like the
    frozen totals, these were hand-written sums of cash + momo + pos, so
    any method not named was excluded from the day's revenue without
    anyone being told. This pins the numbers before they move onto the
    registry.
    """

    def setUp(self):
        self.sheet = self.make_sheet(0)

    def _job(self, method, amount):
        from apps.jobs.models import Job
        return Job.objects.create(
            branch=self.branch, job_type='INSTANT', status=Job.COMPLETE,
            title=f'{method} job', intake_by=self.cashier,
            estimated_cost=Decimal(str(amount)),
            amount_paid=Decimal(str(amount)),
            payment_method=method, daily_sheet=self.sheet,
        )

    def test_breakdown_totals_each_method(self):
        from apps.jobs.selectors.revenue_selectors import get_revenue_breakdown
        from apps.jobs.models import Job

        self._job('CASH', '100.00')
        self._job('CASH',  '50.00')
        self._job('MOMO',  '75.00')
        self._job('POS',   '25.00')

        result = get_revenue_breakdown(Job.objects.filter(daily_sheet=self.sheet))

        self.assertEqual(result['cash'],  Decimal('150.00'))
        self.assertEqual(result['momo'],  Decimal('75.00'))
        self.assertEqual(result['pos'],   Decimal('25.00'))
        self.assertEqual(result['total'], Decimal('250.00'))
        self.assertEqual(result['job_count'], 4)

    def test_credit_is_not_revenue_collected(self):
        """Credit is owed, not received, so it stays out of the total."""
        from apps.jobs.selectors.revenue_selectors import get_revenue_breakdown
        from apps.jobs.models import Job

        self._job('CASH',   '100.00')
        self._job('CREDIT', '300.00')

        result = get_revenue_breakdown(Job.objects.filter(daily_sheet=self.sheet))

        self.assertEqual(result['total'], Decimal('100.00'))

    def test_live_totals_keep_their_key_names(self):
        """The API and the portals read these keys by name."""
        from apps.jobs.selectors.revenue_selectors import get_sheet_live_totals

        self._job('CASH', '100.00')
        self._job('MOMO', '40.00')

        result = get_sheet_live_totals(self.sheet)

        self.assertEqual(result['total_cash'],      Decimal('100.00'))
        self.assertEqual(result['total_momo'],      Decimal('40.00'))
        self.assertEqual(result['total_collected'], Decimal('140.00'))
        self.assertEqual(result['net_cash_in_till'], Decimal('100.00'))

    def test_cashier_summary_keys_are_method_codes(self):
        from apps.jobs.selectors.revenue_selectors import get_cashier_summary

        self._job('CASH', '100.00')
        self._job('POS',   '60.00')

        result = get_cashier_summary(self.branch, self.sheet.date)

        self.assertEqual(result['CASH']['total'], '100.00')
        self.assertEqual(result['POS']['total'],  '60.00')
        self.assertEqual(result['total']['total'], '160.00')
        self.assertEqual(result['total']['count'], 2)

class LiveRevenueTests(RecoveryFixtureMixin, TestCase):
    """
    What the cashier strip and the BM day sheet show while the day is
    still running. Credit settlements are folded into the method
    breakdown here, because money settling a debt is money in the drawer
    the same as any other payment.
    """

    def setUp(self):
        self.sheet = self.make_sheet(0)

    def _job(self, method, amount):
        from apps.jobs.models import Job
        return Job.objects.create(
            branch=self.branch, job_type='INSTANT', status=Job.COMPLETE,
            title=f'{method} job', intake_by=self.cashier,
            estimated_cost=Decimal(str(amount)),
            amount_paid=Decimal(str(amount)),
            payment_method=method, daily_sheet=self.sheet,
        )

    def _settlement(self, method, amount):
        from apps.finance.models import CreditPayment, CreditAccount
        from apps.customers.models import CustomerProfile
        customer = CustomerProfile.objects.create(
            phone=f'0555{amount}'[:10], affiliation_active=True,
            customer_type=CustomerProfile.INDIVIDUAL,
            visit_count=0, total_spend=Decimal('0'),
            tier=CustomerProfile.REGULAR, confidence_score=0,
            is_priority=False, is_walkin=False,
            first_name='Settle', last_name=str(amount),
        )
        account = CreditAccount.objects.create(
            customer=customer, branch=self.branch,
            account_type=CreditAccount.AccountType.INDIVIDUAL,
            status=CreditAccount.Status.ACTIVE,
            credit_limit=Decimal('1000.00'),
            current_balance=Decimal(str(amount)),
            payment_terms=30,
        )
        return CreditPayment.objects.create(
            credit_account=account, daily_sheet=self.sheet,
            received_by=self.cashier, amount=Decimal(str(amount)),
            payment_method=method,
            balance_before=Decimal(str(amount)), balance_after=Decimal('0'),
        )

    def _revenue(self):
        from apps.finance.services.sheet_summary_service import SheetSummaryService
        return SheetSummaryService._live_revenue(self.sheet)

    def test_methods_are_totalled_separately(self):
        self._job('CASH', '100.00')
        self._job('MOMO',  '40.00')
        self._job('POS',   '10.00')

        r = self._revenue()

        self.assertEqual(r['cash'],  '100.00')
        self.assertEqual(r['momo'],  '40.00')
        self.assertEqual(r['pos'],   '10.00')
        self.assertEqual(r['total'], '150.00')
        self.assertTrue(r['is_live'])

    def test_credit_issued_is_reported_but_not_in_the_total(self):
        self._job('CASH',   '100.00')
        self._job('CREDIT', '300.00')

        r = self._revenue()

        self.assertEqual(r['credit_issued'], '300.00')
        self.assertEqual(r['total'],         '100.00')

    def test_settlements_add_into_their_method(self):
        self._job('CASH', '100.00')
        self._settlement('CASH', '60.00')
        self._settlement('MOMO', '25.00')

        r = self._revenue()

        self.assertEqual(r['cash'],           '160.00')
        self.assertEqual(r['momo'],           '25.00')
        self.assertEqual(r['credit_settled'], '85.00')
        self.assertEqual(r['total'],          '185.00')

    def test_net_cash_in_till_is_cash_less_petty(self):
        self._job('CASH', '200.00')
        self.sheet.total_petty_cash_out = Decimal('30.00')
        self.sheet.save(update_fields=['total_petty_cash_out'])

        r = self._revenue()

        self.assertEqual(r['net_cash_in_till'], '170.00')

    def test_online_counts_as_revenue_but_not_as_till_cash(self):
        self._job('CASH',   '100.00')
        self._job('ONLINE', '250.00')

        r = self._revenue()

        self.assertEqual(r['cash'],   '100.00')
        self.assertEqual(r['online'], '250.00')
        self.assertEqual(r['total'],  '350.00')
        self.assertEqual(r['net_cash_in_till'], '100.00')

class EODSummaryRevenueTests(RecoveryFixtureMixin, TestCase):
    """
    The end-of-day summary the BM reads before closing. Same hardcoded
    cash + momo + pos as everywhere else, so the same blind spot.
    """

    def setUp(self):
        self.sheet = self.make_sheet(0)

    def _job(self, method, amount):
        from apps.jobs.models import Job
        return Job.objects.create(
            branch=self.branch, job_type='INSTANT', status=Job.COMPLETE,
            title=f'{method} job', intake_by=self.cashier,
            estimated_cost=Decimal(str(amount)),
            amount_paid=Decimal(str(amount)),
            payment_method=method, daily_sheet=self.sheet,
        )

    def _revenue(self):
        from apps.finance.services.eod_service import EODService
        return EODService.get_summary(self.sheet, self.branch)['revenue']

    def test_methods_are_totalled_separately(self):
        self._job('CASH', '100.00')
        self._job('MOMO',  '40.00')
        self._job('POS',   '10.00')

        r = self._revenue()

        self.assertEqual(r['cash'],  '100.00')
        self.assertEqual(r['momo'],  '40.00')
        self.assertEqual(r['pos'],   '10.00')
        self.assertEqual(r['total'], '150.00')

    def test_credit_is_reported_apart_from_the_total(self):
        self._job('CASH',   '100.00')
        self._job('CREDIT', '300.00')

        r = self._revenue()

        self.assertEqual(r['credit_issued'], '300.00')
        self.assertEqual(r['total'],         '100.00')

    def test_net_cash_is_cash_plus_settlements_less_petty(self):
        self._job('CASH', '200.00')
        self.sheet.total_credit_settled = Decimal('50.00')
        self.sheet.total_petty_cash_out = Decimal('30.00')
        self.sheet.save(update_fields=[
            'total_credit_settled', 'total_petty_cash_out',
        ])

        r = self._revenue()

        self.assertEqual(r['net_cash_in_till'], '220.00')

    def test_online_appears_in_the_eod_summary(self):
        self._job('CASH',   '100.00')
        self._job('ONLINE', '250.00')

        r = self._revenue()

        self.assertEqual(r['online'], '250.00')
        self.assertEqual(r['total'],  '350.00')
        self.assertEqual(r['net_cash_in_till'], '100.00')


class TotalCollectedTests(RecoveryFixtureMixin, TestCase):
    """
    total_collected feeds the weekly filings, the monthly close, the risk
    engines and the BM reports. It was a hardcoded sum of three columns,
    so a new payment method would have been missing from all of them.
    """

    def test_sheet_collected_covers_methods_and_settlements(self):
        sheet = self.make_sheet(0)
        sheet.total_cash            = Decimal('100.00')
        sheet.total_momo            = Decimal('40.00')
        sheet.total_pos             = Decimal('10.00')
        sheet.total_online          = Decimal('250.00')
        sheet.total_credit_issued   = Decimal('500.00')
        sheet.total_credit_settled  = Decimal('25.00')
        sheet.save()

        # Credit issued is owed, not received, so it stays out. Online
        # is the opposite: the branch never touched the money, but it
        # earned it, so it counts.
        self.assertEqual(sheet.total_collected, Decimal('425.00'))

    def test_weekly_collected_is_the_methods_alone(self):
        from apps.finance.models import WeeklyReport
        import datetime

        report = WeeklyReport.objects.create(
            branch=self.branch, week_number=40, year=2026, month=9,
            date_from=timezone.localdate() - datetime.timedelta(days=5),
            date_to=timezone.localdate(),
            total_cash=Decimal('200.00'),
            total_momo=Decimal('75.00'),
            total_pos=Decimal('25.00'),
            total_online=Decimal('250.00'),
            total_credit_issued=Decimal('400.00'),
        )

        self.assertEqual(report.total_collected, Decimal('550.00'))


class PDFRenderTests(RecoveryFixtureMixin, TestCase):
    """
    No PDF in this system has ever had a test. The weekly filing PDF
    raised on every render for months because CoverPage.draw() reached
    for self.canvas instead of self.canv, and the caller's except
    swallowed it. These assert only that real bytes come out, which is
    exactly what nobody was checking.
    """

    def test_weekly_pdf_renders_to_a_real_file(self):
        import os
        from apps.finance.models import WeeklyReport
        from apps.finance.pdf.weekly_report_pdf import _generate_weekly_pdf
        import datetime

        report = WeeklyReport.objects.create(
            branch=self.branch, week_number=40, year=2026, month=9,
            date_from=timezone.localdate() - datetime.timedelta(days=5),
            date_to=timezone.localdate(),
            total_cash=Decimal('200.00'),
            total_momo=Decimal('75.00'),
            total_pos=Decimal('25.00'),
            total_online=Decimal('250.00'),
            total_jobs_created=12,
        )

        _generate_weekly_pdf(report)

        self.assertTrue(report.pdf_path, 'no pdf_path was set')
        self.assertTrue(os.path.exists(report.pdf_path), report.pdf_path)
        with open(report.pdf_path, 'rb') as f:
            head = f.read(5)
        self.assertEqual(head, b'%PDF-')
        self.assertGreater(os.path.getsize(report.pdf_path), 1000)

    def test_monthly_close_pdf_renders_to_bytes(self):
        from apps.finance.models import MonthlyClose
        from apps.finance.monthly_close_engine import MonthlyCloseEngine

        close = MonthlyClose.objects.create(
            branch=self.branch, month=9, year=2026,
            summary_snapshot={
                'revenue': {
                    'total_cash': '200.00', 'total_momo': '75.00',
                    'total_pos': '25.00', 'total_online': '250.00', 'total_collected': '550.00',
                    'cash_pct': 66.7, 'momo_pct': 25.0, 'pos_pct': 8.3, 'online_pct': 58.8,
                },
                'daily': [], 'weekly': [],
            },
        )

        pdf_bytes = MonthlyCloseEngine(self.branch, 9, 2026).generate_pdf(close)

        self.assertTrue(pdf_bytes.startswith(b'%PDF-'))
        self.assertGreater(len(pdf_bytes), 1000)

    def test_invoice_pdf_renders_to_a_real_file(self):
        import os
        from apps.finance.models import Invoice
        from apps.finance.pdf.invoice_pdf import _generate_invoice_pdf

        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number='INV-RTB-TEST-0001',
            total=Decimal('509.00'),
            generated_by=self.bm,
        )

        _generate_invoice_pdf(invoice)

        self.assertTrue(os.path.exists(invoice.pdf_path), invoice.pdf_path)
        with open(invoice.pdf_path, 'rb') as f:
            self.assertEqual(f.read(5), b'%PDF-')

    def test_proforma_pdf_renders_to_bytes(self):
        """
        The proforma is the document customers actually receive, and it
        had no test at all. Its conversion path had never run either —
        the first real acceptance raised NameError.
        """
        from apps.jobs.models import ProformaInvoice
        from apps.jobs.pdf.proforma_pdf import build_proforma_pdf
        import datetime

        from apps.customers.models import CustomerProfile
        customer = CustomerProfile.objects.create(
            phone='0244000000', affiliation_active=True,
            customer_type=CustomerProfile.INDIVIDUAL,
            visit_count=0, total_spend=Decimal('0'),
            tier=CustomerProfile.REGULAR, confidence_score=0,
            is_priority=False, is_walkin=False,
            first_name='Test', last_name='Proforma',
        )

        proforma = ProformaInvoice.objects.create(
            branch=self.branch,
            customer=customer,
            proforma_number='PFI-RTB-2026-00001',
            sequence=1,
            issued_to='Mr Test Customer',
            contact_phone='0244000000',
            valid_until=timezone.localdate() + datetime.timedelta(days=21),
            # The keys build_proforma_pdf actually reads. service_name,
            # quantity, unit_price and total are required; ring_size,
            # output_mode, pages and is_color are optional spec detail.
            line_items=[{
                'service_id': 1,
                'service_name': 'A3 Colour Printing 1-sided',
                'quantity': 1,
                'pages': 18,
                'is_color': True,
                'unit_price': '5.00',
                'total': '90.00',
            }],
            subtotal=Decimal('90.00'),
            total=Decimal('90.00'),
            issued_by=self.bm,
        )

        pdf_bytes = build_proforma_pdf(proforma)

        self.assertTrue(pdf_bytes.startswith(b'%PDF-'))
        self.assertGreater(len(pdf_bytes), 1000)

    def test_day_sheet_pdf_renders_to_a_real_file(self):
        """
        The document produced most often, and the only one that had no
        test — build_data and build_pdf are module-level functions, they
        were just buried in a management command where nothing reached
        for them.
        """
        import os, tempfile
        from apps.finance.pdf.sheet_pdf import build_data, build_pdf

        # Its own branch: make_sheet steps back off Sundays, so two
        # tests asking for different days can land on the same Saturday
        # and collide on the branch+date unique constraint.
        import datetime
        branch = Branch.objects.create(
            name='Sheet PDF Branch', code='SPDF',
            is_headquarters=False, is_regional_hq=False,
            address='1 Sheet Road',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30),
            closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )
        sheet = DailySalesSheet.objects.create(
            branch=branch,
            date=timezone.localdate() - datetime.timedelta(days=1),
            status=DailySalesSheet.Status.CLOSED,
        )
        sheet.total_cash = Decimal('1153.50')
        sheet.total_momo = Decimal('520.50')
        sheet.total_jobs_created = 35
        sheet.save()

        out = os.path.join(tempfile.gettempdir(), f'sheet_test_{sheet.pk}.pdf')
        build_pdf(build_data(sheet), out)

        self.assertTrue(os.path.exists(out), out)
        with open(out, 'rb') as f:
            self.assertEqual(f.read(5), b'%PDF-')
        self.assertGreater(os.path.getsize(out), 1000)