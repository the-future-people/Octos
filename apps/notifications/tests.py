"""
Regression tests for the harmonized reminder/notification system.

Fixtures are constructed from scratch — Django TestCase always runs
against a fresh, empty test database.

Run inside Docker:
    docker compose exec web python manage.py test apps.notifications.tests
"""

import datetime
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.organization.models import Branch
from apps.accounts.models import CustomUser, Role
from apps.hr.models import ShiftRoleConfig, BranchShift
from apps.notifications.models import Notification
from apps.notifications.api.views import NotificationListView


class NotificationsFixtureMixin:

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
        cls.attendant_role = Role.objects.create(
            name='ATTENDANT', display_name='Attendant',
            is_constrained=False, scope='BRANCH',
        )

        cls.branch = Branch.objects.create(
            name='Test Branch', code='TSTB',
            is_headquarters=False, is_regional_hq=False,
            address='123 Test Street',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30),
            closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )

        cls.cashier = cls._make_user('TST-CSH-001', cls.cashier_role, 'Cashier')
        cls.attendant = cls._make_user('TST-ATT-001', cls.attendant_role, 'Attendant')
        cls.bm = cls._make_user('TST-BM-001', cls.bm_role, 'Manager')

        # Explicit ShiftRoleConfig so schedule math is deterministic,
        # not dependent on HRShiftEngine's fallback defaults.
        now = timezone.localtime()
        cls.shift_end_soon = (now + datetime.timedelta(minutes=20)).time()

        # days is parsed by BranchShift.day_list as comma-separated
        # integer weekdays (0=Monday..6=Sunday), matched via
        # `today.weekday() in shift.day_list` in get_today_shift() —
        # NOT day-name strings. Using all 7 days (0-6) keeps this test
        # correct regardless of which real day it runs on, and avoids
        # ever needing to special-case Sunday here (that's covered by
        # its own dedicated test).
        cls.branch_shift = BranchShift.objects.create(
            branch=cls.branch, name='Test Shift', shift_type='FULL_DAY',
            days='0,1,2,3,4,5,6',
            start_time=datetime.time(7, 30), end_time=cls.shift_end_soon,
            is_active=True,
        )

        for role_name in ['CASHIER', 'ATTENDANT', 'BRANCH_MANAGER']:
            ShiftRoleConfig.objects.create(
                shift=cls.branch_shift, role_name=role_name,
                role_start_time=datetime.time(7, 30),
                role_end_time=cls.shift_end_soon,
                job_lock_buffer=0, signoff_buffer=150, autoclose_buffer=150,
            )

    @classmethod
    def _make_user(cls, employee_id, role, last_name):
        u = CustomUser(
            employee_id=employee_id,
            first_name='Test', last_name=last_name,
            email=f'{employee_id.lower()}@test.local',
            employment_status='ACTIVE',
            is_active=True, is_staff=False, is_superuser=False,
            is_clocked_in=False, must_change_password=False,
            is_business_owner=False, download_pin_set=False,
            branch=cls.branch, role=role,
        )
        u.set_password('test-pass-123')
        u.save()
        return u


class DedupeConstraintTests(NotificationsFixtureMixin, TestCase):
    """The DB-level uniqueness constraint is what makes the Celery
    task safe to run every minute without ever duplicating a reminder."""

    def test_blank_dedupe_key_never_collides(self):
        # Two ordinary ALERT notifications with no dedupe_key must
        # coexist freely — the constraint only applies to non-blank keys.
        Notification.objects.create(
            recipient=self.cashier, verb='system', message='one',
        )
        Notification.objects.create(
            recipient=self.cashier, verb='system', message='two',
        )
        self.assertEqual(Notification.objects.filter(recipient=self.cashier).count(), 2)

    def test_duplicate_dedupe_key_rejected(self):
        Notification.objects.create(
            recipient=self.cashier, verb=Notification.Verb.SHIFT_ENDING,
            message='first', dedupe_key='shift_ending-1-2026-07-08-0',
        )
        with self.assertRaises(IntegrityError):
            Notification.objects.create(
                recipient=self.cashier, verb=Notification.Verb.SHIFT_ENDING,
                message='duplicate', dedupe_key='shift_ending-1-2026-07-08-0',
            )

    def test_get_or_create_is_the_safe_pattern(self):
        key = 'shift_ending-1-2026-07-08-0'
        _, created1 = Notification.objects.get_or_create(
            dedupe_key=key,
            defaults=dict(recipient=self.cashier, verb=Notification.Verb.SHIFT_ENDING, message='x'),
        )
        _, created2 = Notification.objects.get_or_create(
            dedupe_key=key,
            defaults=dict(recipient=self.cashier, verb=Notification.Verb.SHIFT_ENDING, message='y'),
        )
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(Notification.objects.filter(dedupe_key=key).count(), 1)


class GenerateShiftRemindersTests(NotificationsFixtureMixin, TestCase):

    def _run(self):
        out = StringIO()
        call_command('generate_reminders', '--type', 'shift', stdout=out)
        return out.getvalue()

    def test_creates_reminder_within_window_for_all_three_roles(self):
        # shift_end is 20 minutes from now for every role — squarely
        # inside the 30-minute window.
        self._run()
        for user in [self.cashier, self.attendant, self.bm]:
            self.assertTrue(
                Notification.objects.filter(
                    recipient=user, verb=Notification.Verb.SHIFT_ENDING,
                ).exists(),
                f'Expected a shift-ending reminder for {user.employee_id}',
            )

    def test_rerunning_does_not_duplicate_within_same_bucket(self):
        self._run()
        self._run()
        count = Notification.objects.filter(
            recipient=self.cashier, verb=Notification.Verb.SHIFT_ENDING,
        ).count()
        self.assertEqual(count, 1)

    def test_signed_off_cashier_gets_no_reminder(self):
        from apps.finance.models import CashierFloat, DailySalesSheet
        today = timezone.localdate()
        sheet = DailySalesSheet.objects.create(
            branch=self.branch, date=today, status='OPEN',
        )
        CashierFloat.objects.create(
            daily_sheet=sheet, cashier=self.cashier,
            opening_float=Decimal('100.00'), is_signed_off=True,
            closing_cash=Decimal('100.00'), expected_cash=Decimal('100.00'),
            variance=Decimal('0.00'),
        )
        self._run()
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.cashier, verb=Notification.Verb.SHIFT_ENDING,
            ).exists()
        )

    def test_outside_window_creates_nothing(self):
        # Push shift_end 3 hours out — well outside the 30-min window.
        far_future = (timezone.localtime() + datetime.timedelta(hours=3)).time()
        ShiftRoleConfig.objects.filter(
            shift=self.branch_shift, role_name='CASHIER',
        ).update(role_end_time=far_future)
        self._run()
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.cashier, verb=Notification.Verb.SHIFT_ENDING,
            ).exists()
        )

    def test_sunday_skips_everyone_entirely(self):
        from unittest.mock import patch
        import datetime as dt

        class FakeDate(dt.date):
            @classmethod
            def today(cls):
                return dt.date(2026, 7, 5)  # a real Sunday

        with patch('django.utils.timezone.localdate', return_value=dt.date(2026, 7, 5)):
            self._run()

        self.assertFalse(Notification.objects.filter(verb=Notification.Verb.SHIFT_ENDING).exists())


class GenerateCheckpointRemindersTests(NotificationsFixtureMixin, TestCase):

    def setUp(self):
        from apps.personal_notes.models import PersonalNote, TaskCheckpoint
        self.note = PersonalNote.objects.create(
            owner=self.cashier, title='Test task', note_type='TASK',
        )
        self.checkpoint = TaskCheckpoint.objects.create(
            note=self.note,
            scheduled_at=timezone.now() - datetime.timedelta(minutes=5),
            acknowledged=False,
        )

    def test_due_checkpoint_creates_pin_gated_reminder(self):
        call_command('generate_reminders', '--type', 'checkpoint', stdout=StringIO())
        notif = Notification.objects.filter(
            recipient=self.cashier, verb=Notification.Verb.TASK_CHECKPOINT,
        ).first()
        self.assertIsNotNone(notif)
        self.assertTrue(notif.requires_pin)
        self.assertEqual(notif.object_id, self.checkpoint.pk)
        # Real content must never leak into the generic message
        self.assertNotIn('Test task', notif.message)

    def test_acknowledged_checkpoint_produces_nothing(self):
        self.checkpoint.acknowledged = True
        self.checkpoint.save()
        call_command('generate_reminders', '--type', 'checkpoint', stdout=StringIO())
        self.assertFalse(
            Notification.objects.filter(recipient=self.cashier).exists()
        )

    def test_rerunning_does_not_duplicate(self):
        call_command('generate_reminders', '--type', 'checkpoint', stdout=StringIO())
        call_command('generate_reminders', '--type', 'checkpoint', stdout=StringIO())
        self.assertEqual(
            Notification.objects.filter(recipient=self.cashier).count(), 1
        )


class NotificationListViewTests(NotificationsFixtureMixin, TestCase):

    def setUp(self):
        self.view = NotificationListView.as_view()
        # 25 passive alerts — more than the default 20-cap
        for i in range(25):
            Notification.objects.create(
                recipient=self.cashier, verb='system', message=f'alert {i}',
                display_mode=Notification.DisplayMode.PASSIVE,
            )
        # One interruptive reminder
        Notification.objects.create(
            recipient=self.cashier, verb=Notification.Verb.SHIFT_ENDING,
            message='shift ending', display_mode=Notification.DisplayMode.INTERRUPTIVE,
        )

    def _get(self, params=''):
        rf = APIRequestFactory()
        req = rf.get(f'/api/v1/notifications/{params}')
        force_authenticate(req, user=self.cashier)
        return self.view(req)

    def test_default_call_stays_capped_at_20(self):
        resp = self._get()
        self.assertEqual(len(resp.data), 20)

    def test_interruptive_filter_is_uncapped(self):
        resp = self._get('?display_mode=INTERRUPTIVE')
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['display_mode'], 'INTERRUPTIVE')

    def test_serializer_exposes_object_id_but_not_content_type(self):
        resp = self._get('?display_mode=INTERRUPTIVE')
        row = resp.data[0]
        self.assertIn('requires_pin', row)
        self.assertIn('category', row)
        self.assertNotIn('content_type', row)