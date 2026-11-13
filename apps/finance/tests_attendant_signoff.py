"""
Attendant sign-off (13 Nov 2026).

The clock is pinned to Wednesday 11 Nov 2026 so every test reads the same
day and time whenever it runs: the attendant's shift ends at 19:30 and the
sign-off deadline is 20:30 (ShiftRoleConfig 19:30 / 0 / 60, as live).

Run inside Docker:
    docker compose exec web python manage.py test apps.finance.tests_attendant_signoff -t .
"""
import datetime
from contextlib import contextmanager
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import CustomUser, Role
from apps.finance.api.attendant_signoff_views import AttendantSignOffSubmitView
from apps.finance.attendant_signoff_engine import AttendantSignOffEngine, SignOffRefused
from apps.finance.models import AttendantSignOff, DailySalesSheet
from apps.hr.models import BranchShift, ShiftRoleConfig
from apps.jobs.models import Job
from apps.notifications.models import Notification
from apps.organization.models import Branch

DAY = datetime.date(2026, 11, 11)   # a Wednesday


def at(hour, minute=0):
    return timezone.make_aware(datetime.datetime.combine(DAY, datetime.time(hour, minute)))


@contextmanager
def clock(hour, minute=0):
    with patch('django.utils.timezone.now', return_value=at(hour, minute)):
        yield at(hour, minute)


class SignOffFixtureMixin:

    @classmethod
    def setUpTestData(cls):
        def role(name, label):
            return Role.objects.create(name=name, display_name=label, is_constrained=False, scope='BRANCH')

        cls.attendant_role = role('ATTENDANT', 'Attendant')
        cls.bm_role = role('BRANCH_MANAGER', 'Branch Manager')
        cls.cashier_role = role('CASHIER', 'Cashier')

        cls.branch = Branch.objects.create(
            name='Sign-off Test Branch', code='SOT',
            is_headquarters=False, is_regional_hq=False,
            address='1 Test Road',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30),
            closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )
        shift = BranchShift.objects.create(
            branch=cls.branch, name='SOT Main Shift', shift_type='FULL_DAY',
            days='0,1,2,3,4,5', start_time=datetime.time(8, 0),
            end_time=datetime.time(19, 30), is_active=True,
        )
        ShiftRoleConfig.objects.create(
            shift=shift, role_name='ATTENDANT',
            role_start_time=datetime.time(8, 0), role_end_time=datetime.time(19, 30),
            job_lock_buffer=0, signoff_buffer=60, autoclose_buffer=None,
        )

        cls.attendant = cls._user('SOT-ATT-001', cls.attendant_role, 'Attendant')
        cls.other_attendant = cls._user('SOT-ATT-002', cls.attendant_role, 'Second')
        cls.bm = cls._user('SOT-BM-001', cls.bm_role, 'Manager')
        cls.cashier = cls._user('SOT-CSH-001', cls.cashier_role, 'Cashier')

        cls.sheet = DailySalesSheet.objects.create(branch=cls.branch, date=DAY, status='OPEN')

    @classmethod
    def _user(cls, employee_id, role, last_name, active=True):
        u = CustomUser(
            employee_id=employee_id, first_name='Test', last_name=last_name,
            email=f'{employee_id.lower()}@signoff.test', employment_status='ACTIVE',
            is_active=active, branch=cls.branch, role=role,
        )
        u.set_password('test-pass-123')
        u.save()
        return u

    def job(self, job_type='INSTANT', status='PENDING_PAYMENT', payment='UNPAID',
            work='RECEIVED', handover='AWAITING_COLLECTION', cost='50.00', by=None, sheet=None):
        return Job.objects.create(
            branch=self.branch, job_type=job_type, title=f'{job_type} job',
            status=status, payment_state=payment, work_state=work, handover_state=handover,
            estimated_cost=Decimal(cost), daily_sheet=sheet or self.sheet,
            intake_by=by or self.attendant,
        )

    def octos(self):
        role = Role.objects.create(name='OCTOS', display_name='Octos', is_constrained=False, scope='HQ')
        return self._user('OCTOS', role, '(assistant)', active=False)

    def engine(self):
        return AttendantSignOffEngine(self.branch)


class BucketTests(SignOffFixtureMixin, TestCase):

    def test_every_job_lands_in_exactly_one_bucket(self):
        self.job('INSTANT', status='COMPLETE', payment='SETTLED', work='DONE', handover='HANDED_OVER')
        self.job('INSTANT')                                                   # unpaid instant
        self.job('PRODUCTION', status='PAID', payment='DEPOSIT_PAID')         # handed to production
        self.job('PRODUCTION')                                                # awaiting deposit
        self.job('INSTANT', status='DRAFT')
        self.job('INSTANT', status='CANCELLED')
        self.job('INSTANT', by=self.other_attendant)                          # someone else's

        with clock(19, 45):
            b = self.engine().preview(self.attendant, self.sheet)['buckets']

        self.assertEqual(b['paid'], 1)
        self.assertEqual(b['unpaid_instant'], 1)
        self.assertEqual(b['handed_to_production'], 1)
        self.assertEqual(b['awaiting_deposit'], 1)
        self.assertEqual(b['draft'], 1)
        self.assertEqual(b['cancelled'], 1)
        self.assertEqual(b['recorded_total'], 6)
        self.assertEqual(sum(v for k, v in b.items() if k != 'recorded_total'), b['recorded_total'])

    def test_shelf_holds_ready_uncollected_production_work_from_any_day(self):
        ready = self.job('PRODUCTION', status='READY', payment='SETTLED', work='DONE', by=self.other_attendant)
        self.job('PRODUCTION', status='COMPLETE', payment='SETTLED', work='DONE', handover='HANDED_OVER')
        self.job('INSTANT', status='COMPLETE', payment='SETTLED', work='DONE', handover='AWAITING_COLLECTION')
        with clock(19, 45):
            shelf = self.engine().preview(self.attendant, self.sheet)['shelf']
        self.assertEqual([r['id'] for r in shelf], [ready.pk])


class TimingTests(SignOffFixtureMixin, TestCase):

    def test_phases_follow_the_shift(self):
        engine = self.engine()
        expected = [((18, 0), 'OPEN'), ((19, 10), 'CLOSING_SOON'), ((19, 45), 'SIGN_OFF_OPEN'),
                    ((20, 20), 'FINAL_CALL'), ((20, 40), 'OVERDUE')]
        for (h, m), phase in expected:
            with clock(h, m) as now:
                self.assertEqual(engine.status(self.attendant, now=now)['phase'], phase, f'{h}:{m:02d}')

    def test_sign_off_opens_at_shift_end_not_before(self):
        self.job('INSTANT', status='COMPLETE', payment='SETTLED', work='DONE', handover='HANDED_OVER')
        with clock(19, 20) as now:
            self.assertFalse(self.engine().status(self.attendant, now=now)['can_sign_off'])
            with self.assertRaises(SignOffRefused):
                self.engine().submit(self.attendant, {}, {}, now=now)
        with clock(19, 31) as now:
            self.assertTrue(self.engine().status(self.attendant, now=now)['can_sign_off'])

    def test_no_shift_configured_falls_back_to_the_live_times(self):
        from apps.hr.shift_engine import ShiftEngine
        bare = Branch.objects.create(
            name='Bare Branch', code='BAR', is_headquarters=False, is_regional_hq=False,
            address='2 Test Road', capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30), closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'), nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )
        with clock(12, 0):
            s = ShiftEngine(bare).get_role_schedule('ATTENDANT')
        self.assertEqual(datetime.datetime.fromisoformat(s['job_lock_at']), at(19, 30))
        self.assertEqual(datetime.datetime.fromisoformat(s['signoff_at']), at(20, 30))


class SubmitTests(SignOffFixtureMixin, TestCase):

    def test_every_unpaid_instant_job_must_be_answered(self):
        a = self.job('INSTANT')
        self.job('INSTANT')
        with clock(19, 45) as now, self.assertRaises(SignOffRefused):
            self.engine().submit(self.attendant, {a.pk: 'COMING_BACK'}, {}, now=now)
        self.assertFalse(AttendantSignOff.objects.exists())

    def test_answers_are_recorded_and_not_printed_is_cancelled(self):
        back = self.job('INSTANT', cost='30.00')
        left = self.job('INSTANT', cost='80.00')
        never = self.job('INSTANT', cost='20.00')
        shelf = self.job('PRODUCTION', status='READY', payment='SETTLED', work='DONE')

        with clock(19, 45) as now, self.captureOnCommitCallbacks(execute=True):
            record = self.engine().submit(
                self.attendant,
                {back.pk: 'COMING_BACK', left.pk: 'LEFT_UNPAID', never.pk: 'NOT_PRODUCED'},
                {shelf.pk: 'MISSING'},
                handover_note='Mr Mensah returns at 9',
                now=now,
            )

        self.assertFalse(record.is_auto)
        self.assertEqual(record.signed_off_by, self.attendant)
        self.assertEqual(record.left_unpaid_value, Decimal('80.00'))
        self.assertEqual(record.missing_count, 1)
        self.assertEqual(record.items.count(), 4)
        self.assertEqual(record.buckets['unpaid_instant'], 2)
        self.assertEqual(record.buckets['cancelled'], 1)

        never.refresh_from_db()
        left.refresh_from_db()
        self.assertEqual(never.status, 'CANCELLED')
        self.assertEqual(left.status, 'PENDING_PAYMENT')     # testimony only: the BM decides

        self.assertTrue(Notification.objects.filter(recipient=self.bm).exists())

    def test_only_once(self):
        with clock(19, 45) as now:
            self.engine().submit(self.attendant, {}, {}, now=now)
            with self.assertRaises(SignOffRefused):
                self.engine().submit(self.attendant, {}, {}, now=now)

    def test_only_an_attendant_signs_off(self):
        with clock(19, 45) as now, self.assertRaises(SignOffRefused):
            self.engine().submit(self.cashier, {}, {}, now=now)

    def test_submit_endpoint(self):
        j = self.job('INSTANT')
        request = APIRequestFactory().post(
            '/api/v1/finance/attendant/signoff/',
            {'unpaid': {str(j.pk): 'COMING_BACK'}, 'shelf': {}}, format='json',
        )
        force_authenticate(request, user=self.attendant)
        with clock(19, 45):
            res = AttendantSignOffSubmitView.as_view()(request)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(AttendantSignOff.objects.filter(attendant=self.attendant).exists())


class AutoSignOffTests(SignOffFixtureMixin, TestCase):

    def test_nothing_happens_before_the_deadline(self):
        self.job('INSTANT')
        self.octos()
        with clock(20, 20) as now:
            self.assertEqual(self.engine().auto_signoff(self.sheet, now=now), [])

    def test_octos_signs_off_whoever_is_due_once(self):
        self.job('INSTANT')
        octos = self.octos()
        with clock(20, 35) as now:
            created = self.engine().auto_signoff(self.sheet, now=now)
            again = self.engine().auto_signoff(self.sheet, now=now)
        self.assertEqual(len(created), 1)
        self.assertEqual(again, [])
        record = created[0]
        self.assertTrue(record.is_auto)
        self.assertEqual(record.signed_off_by, octos)
        self.assertEqual(record.signed_off_at, at(20, 30))
        self.assertEqual(record.buckets['unpaid_instant'], 1)
        self.assertTrue(Notification.objects.filter(recipient=self.bm).exists())

    def test_attendants_with_no_jobs_are_not_due(self):
        self.octos()
        with clock(20, 35) as now:
            self.assertEqual(self.engine().auto_signoff(self.sheet, now=now), [])

    def test_a_missing_octos_account_fails_loudly(self):
        self.job('INSTANT')
        with clock(20, 35) as now, self.assertRaises(RuntimeError):
            self.engine().auto_signoff(self.sheet, now=now)

    def test_scheduled_command(self):
        self.job('INSTANT')
        self.octos()
        with clock(20, 35):
            call_command('run_sheet_tasks', 'attendant_signoff', stdout=StringIO())
        self.assertTrue(AttendantSignOff.objects.filter(attendant=self.attendant, is_auto=True).exists())


class ManagerTests(SignOffFixtureMixin, TestCase):

    def test_gate_waits_for_attendants_who_recorded_jobs(self):
        self.job('INSTANT', status='COMPLETE', payment='SETTLED', work='DONE', handover='HANDED_OVER')
        with clock(19, 50) as now:
            self.assertFalse(self.engine().gate(self.sheet, now=now)['passed'])
            self.engine().submit(self.attendant, {}, {}, now=now)
            self.assertTrue(self.engine().gate(self.sheet, now=now)['passed'])

    def test_gate_signs_off_overdue_attendants_itself(self):
        self.job('INSTANT', status='COMPLETE', payment='SETTLED', work='DONE', handover='HANDED_OVER')
        self.octos()
        with clock(20, 31) as now:
            self.assertTrue(self.engine().gate(self.sheet, now=now)['passed'])

    def _left_unpaid_item(self):
        left = self.job('INSTANT', cost='80.00')
        with clock(19, 45) as now:
            record = self.engine().submit(self.attendant, {left.pk: 'LEFT_UNPAID'}, {}, now=now)
        return left, record.items.get()

    def test_manager_writes_off_a_job_left_unpaid(self):
        left, item = self._left_unpaid_item()
        with clock(20, 0):
            AttendantSignOffEngine.resolve_item(item.pk, self.bm, note='Customer walked out')
        item.refresh_from_db()
        left.refresh_from_db()
        self.assertFalse(item.needs_bm)
        self.assertEqual(item.resolved_by, self.bm)
        self.assertEqual(left.status, 'CANCELLED')

    def test_resolving_needs_a_manager_and_a_reason(self):
        _, item = self._left_unpaid_item()
        with clock(20, 0):
            with self.assertRaises(SignOffRefused):
                AttendantSignOffEngine.resolve_item(item.pk, self.attendant, note='x')
            with self.assertRaises(SignOffRefused):
                AttendantSignOffEngine.resolve_item(item.pk, self.bm, note='  ')

    def test_overview_lists_open_items(self):
        _, item = self._left_unpaid_item()
        with clock(20, 0):
            overview = self.engine().sheet_overview(self.sheet)
        row = overview['attendants'][0]
        self.assertTrue(overview['all_signed_off'])
        self.assertEqual([i['id'] for i in row['open_items']], [item.pk])


class ReminderTests(SignOffFixtureMixin, TestCase):

    def _run(self, hour, minute):
        with clock(hour, minute):
            call_command('generate_reminders', '--type', 'shift', stdout=StringIO())

    def _signoff_reminders(self, user):
        return Notification.objects.filter(recipient=user, link='signoff')

    def test_attendant_with_jobs_is_reminded_to_sign_off(self):
        self.job('INSTANT')
        self._run(19, 45)
        self.assertTrue(self._signoff_reminders(self.attendant).exists())

    def test_attendant_without_jobs_is_not(self):
        self._run(19, 45)
        self.assertFalse(self._signoff_reminders(self.attendant).exists())

    def test_signed_off_attendant_is_not(self):
        self.job('INSTANT', status='COMPLETE', payment='SETTLED', work='DONE', handover='HANDED_OVER')
        with clock(19, 40) as now:
            self.engine().submit(self.attendant, {}, {}, now=now)
        self._run(19, 45)
        self.assertFalse(self._signoff_reminders(self.attendant).exists())
