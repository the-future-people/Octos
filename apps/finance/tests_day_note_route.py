"""
One address, two notes (18 Nov 2026). /finance/sheets/<pk>/notes/ was
routed twice: first to the sheet's own note (PATCH), then to the notes that
explain a day (POST). Django took the first, so every explanation written
while reviewing a month was refused with 405 and nothing was saved.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, Role
from apps.communications.tests import make_org
from apps.finance.models import DailySalesSheet, DaySheetNote


class DayNoteRouteTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org('-DN')
        role = Role.objects.get_or_create(name='BRANCH_MANAGER', defaults={
            'display_name': 'Branch Manager', 'is_constrained': False, 'scope': 'BRANCH'})[0]
        cls.bm = CustomUser(employee_id='DN-1', first_name='Ama', last_name='Test', email='dn-1@test.local',
                            employment_status='ACTIVE', is_active=True, branch=cls.branch, role=role)
        cls.bm.set_password('test-pass-123')
        cls.bm.save()
        cls.closed = DailySalesSheet.objects.create(branch=cls.branch, date=date(2026, 11, 13), status='CLOSED',
                                                    total_jobs_created=9, total_cash=Decimal('4200.00'))
        cls.open = DailySalesSheet.objects.create(branch=cls.branch, date=date(2026, 11, 18), status='OPEN')

    def setUp(self):
        self.client = APIClient(HTTP_HOST='localhost')
        self.client.force_authenticate(self.bm)

    def test_explaining_a_day_saves_the_note(self):
        res = self.client.post(f'/api/v1/finance/sheets/{self.closed.pk}/notes/',
                               {'body': 'A bulk order from a school.'}, format='json')
        self.assertIn(res.status_code, (200, 201), res.content)
        self.assertEqual(DaySheetNote.objects.filter(daily_sheet=self.closed).count(), 1)

    def test_the_sheets_own_note_still_saves(self):
        res = self.client.patch(f'/api/v1/finance/sheets/{self.open.pk}/notes/', {'notes': 'Printer 2 is down.'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.open.refresh_from_db()
        self.assertEqual(self.open.notes, 'Printer 2 is down.')
