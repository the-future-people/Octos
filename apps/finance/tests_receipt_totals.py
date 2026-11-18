"""
The receipts list's takings (18 Nov 2026): the phone's Receipts shows the
period's total and the split by method. They are counted over every receipt
in the period, not just the page shown, and voided receipts are not counted.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, Role
from apps.communications.tests import make_org
from apps.finance.models import DailySalesSheet, Receipt
from apps.jobs.models import Job


class ReceiptTotalsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org('-RT')
        role = Role.objects.get_or_create(name='BRANCH_MANAGER', defaults={
            'display_name': 'Branch Manager', 'is_constrained': False, 'scope': 'BRANCH'})[0]
        cls.bm = CustomUser(employee_id='RT-1', first_name='Ama', last_name='Test', email='rt-1@test.local',
                            employment_status='ACTIVE', is_active=True, branch=cls.branch, role=role)
        cls.bm.set_password('test-pass-123')
        cls.bm.save()
        sheet = DailySalesSheet.objects.create(branch=cls.branch, date=timezone.localdate(), status='OPEN')
        job = Job.objects.create(branch=cls.branch, job_type=Job.INSTANT, title='Photocopy', status=Job.PAID,
                                 estimated_cost=Decimal('100.00'))
        rows = [('CASH', '10.00', False), ('CASH', '15.50', False), ('MOMO', '40.00', False),
                ('POS', '7.10', False), ('CASH', '99.00', True)]    # the last is voided
        for i, (method, amount, void) in enumerate(rows):
            Receipt.objects.create(job=job, daily_sheet=sheet, receipt_number=f'RCP-RT-{i}', sequence=i,
                                   payment_method=method, amount_paid=Decimal(amount), is_void=void,
                                   momo_reference='', pos_approval_code='', customer_name='Walk-in',
                                   customer_phone='', company_name='')

    def get(self, **params):
        client = APIClient()
        client.force_authenticate(self.bm)
        r = client.get('/api/v1/finance/receipts/', params)
        self.assertEqual(r.status_code, 200, r.content[:300])
        return r.data

    def test_totals_cover_the_period_not_the_page(self):
        data = self.get(period='day', page_size=2)
        self.assertEqual(len(data['results']), 2)
        self.assertEqual(data['totals']['amount'], '72.60')
        self.assertEqual(data['totals']['count'], 4)

    def test_split_by_method_leaves_out_voided(self):
        by = self.get(period='day')['totals']['by_method']
        self.assertEqual(by['CASH'], {'amount': '25.50', 'count': 2})
        self.assertEqual(by['MOMO'], {'amount': '40.00', 'count': 1})
        self.assertEqual(by['POS'], {'amount': '7.10', 'count': 1})
