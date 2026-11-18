"""
Searching jobs (18 Nov 2026): the phone's Jobs page searches by name, phone
or job number. The search pointed at customer fields that no longer exist
(contact_name, contact_phone), so every search was a server error.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, Role
from apps.communications.tests import make_org
from apps.customers.models import CustomerProfile
from apps.jobs.models import Job


class JobSearchTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org('-JS')
        role = Role.objects.get_or_create(name='BRANCH_MANAGER', defaults={
            'display_name': 'Branch Manager', 'is_constrained': False, 'scope': 'BRANCH'})[0]
        cls.bm = CustomUser(employee_id='JS-1', first_name='Ama', last_name='Test', email='js-1@test.local',
                            employment_status='ACTIVE', is_active=True, branch=cls.branch, role=role)
        cls.bm.set_password('test-pass-123')
        cls.bm.save()
        selorm = CustomerProfile.objects.create(phone='0244000011', first_name='Selorm', last_name='Agbeko')
        efua = CustomerProfile.objects.create(phone='0244000099', first_name='Efua', last_name='Sarpong')
        cls.a = Job.objects.create(branch=cls.branch, job_type=Job.INSTANT, title='Photocopy', status=Job.PAID,
                                   estimated_cost=Decimal('5.00'), customer=selorm)
        cls.b = Job.objects.create(branch=cls.branch, job_type=Job.INSTANT, title='Flyers', status=Job.PAID,
                                   estimated_cost=Decimal('25.00'), customer=efua)

    def search(self, words):
        client = APIClient()
        client.force_authenticate(self.bm)
        r = client.get('/api/v1/jobs/', {'search': words})
        self.assertEqual(r.status_code, 200, r.content[:300])
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        return {row['id'] for row in rows}

    def test_by_first_name_last_name_and_both(self):
        self.assertEqual(self.search('Selorm'), {self.a.id})
        self.assertEqual(self.search('agbeko'), {self.a.id})
        self.assertEqual(self.search('Selorm Agbeko'), {self.a.id})

    def test_by_phone_and_part_of_a_phone(self):
        self.assertEqual(self.search('0244000099'), {self.b.id})
        self.assertEqual(self.search('000099'), {self.b.id})

    def test_by_job_number_and_title(self):
        self.assertEqual(self.search(self.b.job_number.split('-')[-1]), {self.b.id})
        self.assertEqual(self.search('Flyers'), {self.b.id})
