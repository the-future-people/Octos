"""
Breaks (16 Nov 2026): "Taking a break" and "I'm back" from the are-you-there
check, and the Branch Manager told once a break passes 30 minutes.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, Role
from apps.analytics.breaks import alert_long_breaks
from apps.analytics.models import UserSession
from apps.communications.tests import make_org


class BreakTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org('-BR')
        roles = {name: Role.objects.get_or_create(name=name, defaults={
                     'display_name': name.title(), 'is_constrained': False, 'scope': 'BRANCH'})[0]
                 for name in ('ATTENDANT', 'BRANCH_MANAGER')}
        cls.kofi = cls.user('BR-ATT', 'Kofi', roles['ATTENDANT'])
        cls.manager = cls.user('BR-BM', 'Yaw', roles['BRANCH_MANAGER'])

    @classmethod
    def user(cls, employee_id, name, role):
        u = CustomUser(employee_id=employee_id, first_name=name, last_name='Test',
                       email=f'{employee_id.lower()}@test.local', employment_status='ACTIVE',
                       is_active=True, branch=cls.branch, role=role)
        u.set_password('test-pass-123')
        u.save()
        return u

    def setUp(self):
        now = timezone.now()
        self.session = UserSession.objects.create(user=self.kofi, branch=self.branch, portal='ATTENDANT',
                                                  started_at=now - timedelta(hours=2), last_seen_at=now - timedelta(minutes=31))
        self.api = APIClient()
        self.api.force_authenticate(self.kofi)

    def test_taking_a_break_and_coming_back(self):
        response = self.api.post('/api/v1/analytics/session/break/', {'on': True}, format='json')
        self.assertTrue(response.data['on_break'])
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.on_break_since)
        self.api.post('/api/v1/analytics/session/break/', {'on': False}, format='json')
        self.session.refresh_from_db()
        self.assertIsNone(self.session.on_break_since)
        self.assertGreater(self.session.last_seen_at, timezone.now() - timedelta(seconds=5))   # back = active

    def test_no_open_session(self):
        self.session.ended_at = timezone.now()
        self.session.save()
        self.assertEqual(self.api.post('/api/v1/analytics/session/break/', {'on': True}, format='json').status_code, 404)

    @patch('apps.notifications.services.notify')
    def test_the_manager_is_told_once_after_thirty_minutes(self, notify):
        self.session.on_break_since = timezone.now() - timedelta(minutes=31)
        self.session.save()
        self.assertEqual(alert_long_breaks(), 1)
        self.assertEqual(notify.call_args.kwargs['recipient'], self.manager)
        self.assertEqual(notify.call_args.kwargs['message'], 'Kofi Test has been on break for 31 minutes.')
        self.assertEqual(alert_long_breaks(), 0)     # once

    @patch('apps.notifications.services.notify')
    def test_a_short_break_tells_nobody(self, notify):
        self.session.on_break_since = timezone.now() - timedelta(minutes=10)
        self.session.save()
        self.assertEqual(alert_long_breaks(), 0)
        notify.assert_not_called()
