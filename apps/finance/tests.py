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
        """An open sheet dated some number of days before today."""
        d = timezone.localdate() - datetime.timedelta(days=days_ago)
        # Step back off Sunday — recovery ignores days the branch never traded.
        while d.weekday() == 6:
            d -= datetime.timedelta(days=1)
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