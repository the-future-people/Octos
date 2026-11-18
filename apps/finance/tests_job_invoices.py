"""
A job's invoices (18 Nov 2026): the job page asks for ?job=<id>. The list
ignored it and returned the branch's newest invoice, so every job looked
invoiced already. And the job page's own invoice call must be one the server
takes: a tax invoice, sent by WhatsApp (PROFORMA and DOWNLOAD were refused).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, Role
from apps.communications.tests import make_org
from apps.jobs.models import Job


class JobInvoiceTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org('-JI')
        role = Role.objects.get_or_create(name='BRANCH_MANAGER', defaults={
            'display_name': 'Branch Manager', 'is_constrained': False, 'scope': 'BRANCH'})[0]
        cls.bm = CustomUser(employee_id='JI-1', first_name='Ama', last_name='Test', email='ji-1@test.local',
                            employment_status='ACTIVE', is_active=True, branch=cls.branch, role=role)
        cls.bm.set_password('test-pass-123')
        cls.bm.save()
        cls.a, cls.b = (Job.objects.create(branch=cls.branch, job_type=Job.INSTANT, title=title, status=Job.PAID,
                                           estimated_cost=Decimal('20.00')) for title in ('Photocopy', 'Flyers'))

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.bm)

    def make_invoice(self, job):
        # Exactly what the job page sends (jobFileQuery.useJobFile).
        return self.client.post('/api/v1/finance/invoices/create/', {
            'job_id': job.id, 'invoice_type': 'TAX', 'delivery_channel': 'WHATSAPP',
            'bill_to_name': 'Selorm Agbeko', 'bill_to_phone': '0244000011', 'bill_to_email': '', 'bill_to_company': '', 'bm_note': '',
        }, format='json')

    def ids(self, **params):
        r = self.client.get('/api/v1/finance/invoices/', params)
        self.assertEqual(r.status_code, 200)
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        return [row['id'] for row in rows]

    def test_the_job_pages_call_is_accepted(self):
        r = self.make_invoice(self.a)
        self.assertEqual(r.status_code, 201, r.content[:300])
        self.assertEqual(r.data['invoice_type'], 'TAX')

    def test_a_job_sees_only_its_own_invoices(self):
        inv = self.make_invoice(self.a).data['id']
        self.assertEqual(self.ids(job=self.a.id), [inv])
        self.assertEqual(self.ids(job=self.b.id), [])
        self.assertEqual(self.ids(), [inv])
