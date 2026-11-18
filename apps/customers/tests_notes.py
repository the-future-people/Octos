"""
A customer's notes (18 Nov 2026): the profile saves the Branch Manager's
notes with PATCH /customers/<id>/edit/ {notes}. 'notes' was not an editable
field for any kind of customer, so every save was refused.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, Role
from apps.communications.tests import make_org
from apps.customers.models import CustomerProfile


class CustomerNotesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        branch = make_org('-CN')
        role = Role.objects.get_or_create(name='BRANCH_MANAGER', defaults={
            'display_name': 'Branch Manager', 'is_constrained': False, 'scope': 'BRANCH'})[0]
        cls.bm = CustomUser(employee_id='CN-1', first_name='Ama', last_name='Test', email='cn-1@test.local',
                            employment_status='ACTIVE', is_active=True, branch=branch, role=role)
        cls.bm.set_password('test-pass-123')
        cls.bm.save()

    def test_notes_save_for_every_kind_of_customer(self):
        client = APIClient()
        client.force_authenticate(self.bm)
        for i, kind in enumerate(['INDIVIDUAL', 'BUSINESS', 'INSTITUTION']):
            c = CustomerProfile.objects.create(phone=f'024400{i:04d}', first_name='Efua', customer_type=kind,
                                               company_name='' if kind == 'INDIVIDUAL' else 'Suma Court')
            r = client.patch(f'/api/v1/customers/{c.id}/edit/', {'notes': 'Pays by MoMo.'}, format='json')
            self.assertEqual(r.status_code, 200, r.content[:300])
            c.refresh_from_db()
            self.assertEqual(c.notes, 'Pays by MoMo.')
