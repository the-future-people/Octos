"""
Filing a week makes its PDF (18 Nov 2026). The service imported the PDF
builder from the wrong module, so the import failed inside a try that only
logged it. Every week was locked without a document, and the filing list,
which shows its share button only when a week has one, never offered it.
"""
import os
from unittest import mock
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import CustomUser, Role
from apps.communications.tests import make_org
from apps.finance.models import DailySalesSheet, WeeklyReport
from apps.finance.services.weekly_report_service import WeeklyReportService


class WeeklyPdfOnSubmitTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org('-WP')
        role = Role.objects.get_or_create(name='BRANCH_MANAGER', defaults={
            'display_name': 'Branch Manager', 'is_constrained': False, 'scope': 'BRANCH'})[0]
        cls.bm = CustomUser(employee_id='WP-1', first_name='Ama', last_name='Test', email='wp-1@test.local',
                            employment_status='ACTIVE', is_active=True, branch=cls.branch, role=role)
        cls.bm.set_password('test-pass-123')
        cls.bm.save()
        # A finished week inside one month: Monday 2 to Saturday 7 November.
        monday = date(2026, 11, 2)
        for i in range(6):
            DailySalesSheet.objects.create(
                branch=cls.branch, date=monday + timedelta(days=i), status='CLOSED',
                total_jobs_created=10, total_cash=Decimal('300.00'), total_momo=Decimal('200.00'))

    def test_submitting_a_week_writes_its_pdf(self):
        report, _ = WeeklyReportService.prepare(self.branch, today=date(2026, 11, 7))
        report, errors = WeeklyReportService.submit(report, submitted_by=self.bm)

        self.assertEqual(errors, [])
        report.refresh_from_db()
        self.assertEqual(report.status, WeeklyReport.Status.LOCKED)
        self.assertTrue(report.pdf_path, 'the filed week has no PDF')
        self.assertTrue(os.path.exists(report.pdf_path))
        os.remove(report.pdf_path)


class PrepareLeavesFiledWeeksAloneTests(TestCase):
    """
    The portal asks for the outstanding week on every load, and that
    prepares it. Prepare saved the whole row it had read, so a week filed
    while it ran was written back to a draft: the manager filed, the block
    came straight back, and the PDF was lost (18 Nov 2026).
    """

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org('-WR')
        role = Role.objects.get_or_create(name='BRANCH_MANAGER', defaults={
            'display_name': 'Branch Manager', 'is_constrained': False, 'scope': 'BRANCH'})[0]
        cls.bm = CustomUser(employee_id='WR-1', first_name='Kofi', last_name='Test', email='wr-1@test.local',
                            employment_status='ACTIVE', is_active=True, branch=cls.branch, role=role)
        cls.bm.set_password('test-pass-123')
        cls.bm.save()
        monday = date(2026, 11, 9)
        for i in range(6):
            DailySalesSheet.objects.create(
                branch=cls.branch, date=monday + timedelta(days=i), status='CLOSED',
                total_jobs_created=5, total_cash=Decimal('100.00'))

    def test_a_week_filed_while_prepare_runs_stays_filed(self):
        report, _ = WeeklyReportService.prepare(self.branch, today=date(2026, 11, 14))

        # Filed in the middle of the next prepare, after it has read the row.
        def file_meanwhile(*args, **kwargs):
            WeeklyReport.objects.filter(pk=report.pk).update(
                status=WeeklyReport.Status.LOCKED, pdf_path='/tmp/w46.pdf')
            return {}

        with mock.patch('apps.inventory.inventory_engine.InventoryEngine.generate_weekly_snapshot',
                        side_effect=file_meanwhile):
            WeeklyReportService.prepare(self.branch, today=date(2026, 11, 14))

        report.refresh_from_db()
        self.assertEqual(report.status, WeeklyReport.Status.LOCKED)
        self.assertEqual(report.pdf_path, '/tmp/w46.pdf')

    def test_preparing_a_filed_week_changes_nothing(self):
        report, _ = WeeklyReportService.prepare(self.branch, today=date(2026, 11, 14))
        WeeklyReport.objects.filter(pk=report.pk).update(status=WeeklyReport.Status.LOCKED, total_cash=Decimal('600.00'))
        DailySalesSheet.objects.filter(branch=self.branch, date=date(2026, 11, 10)).update(total_cash=Decimal('999.00'))

        again, created = WeeklyReportService.prepare(self.branch, today=date(2026, 11, 14))

        self.assertFalse(created)
        again.refresh_from_db()
        self.assertEqual(again.status, WeeklyReport.Status.LOCKED)
        self.assertEqual(again.total_cash, Decimal('600.00'))
