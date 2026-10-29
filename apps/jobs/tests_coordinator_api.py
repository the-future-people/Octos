"""
The coordinator's endpoints, called the way the portal calls them.

Through the API rather than the services underneath, because the views
load jobs their own way (prefetched, filtered by the user's branch) and
that is where today's clearing bug lived while every service test passed.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.jobs.models import Job
from apps.jobs.tests import JobsFixtureMixin

QUEUE = '/api/v1/jobs/coordinator/verification-queue/'
BOARD = '/api/v1/jobs/coordinator/board/'


def inspect(pk):
    return f'/api/v1/jobs/{pk}/inspect/'


def release(pk):
    return f'/api/v1/jobs/{pk}/inspect/release/'


def verify(pk):
    return f'/api/v1/jobs/{pk}/verify/'


class CoordinatorApiTests(JobsFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.kojo = User(
            employee_id='TST-FC-003',
            first_name='Kojo', last_name='Mensah',
            email='kojo.api@test.local',
            employment_status='ACTIVE',
            is_active=True, is_staff=False, is_superuser=False,
            is_clocked_in=False, must_change_password=False,
            is_business_owner=False, download_pin_set=False,
            branch=cls.branch, role=cls.coordinator_role,
        )
        cls.kojo.set_password('test-pass-123')
        cls.kojo.save()

    def setUp(self):
        # Live updates go out over the broadcast channel; nothing here
        # is listening, and a test must not need it running.
        quiet = patch('apps.core.broadcast.broadcast_invalidation')
        quiet.start()
        self.addCleanup(quiet.stop)

        self.me = APIClient()
        self.me.force_authenticate(user=self.coordinator)
        self.other = APIClient()
        self.other.force_authenticate(user=self.kojo)

    def _job(self, promise_in_hours=1, **overrides):
        defaults = dict(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PAID, title='API test',
            intake_by=None, estimated_cost=Decimal('100.00'),
            daily_sheet=self.sheet, intake_channel='ONLINE',
            payment_state='SETTLED', work_state='RECEIVED',
            handover_state='AWAITING_COLLECTION',
            estimated_ready_at=timezone.now() + timedelta(hours=promise_in_hours),
        )
        defaults.update(overrides)
        return Job.objects.create(**defaults)

    # ── The queue ────────────────────────────────────────────────

    def test_the_queue_marks_exactly_one_job_next(self):
        first = self._job(promise_in_hours=1)
        self._job(promise_in_hours=2)

        rows = self.me.get(QUEUE).json()
        self.assertEqual([r['is_next'] for r in rows], [True, False])
        self.assertEqual(rows[0]['id'], first.pk)

    def test_the_queue_shows_who_holds_a_job(self):
        first = self._job(promise_in_hours=1)
        second = self._job(promise_in_hours=2)
        self.assertEqual(self.me.post(inspect(first.pk)).status_code, 200)

        rows = self.other.get(QUEUE).json()
        self.assertIsNotNone(rows[0]['inspecting_by_name'])
        self.assertFalse(rows[0]['inspecting_is_me'])
        self.assertTrue(rows[1]['is_next'])
        self.assertEqual(rows[1]['id'], second.pk)

    # ── Taking a job ─────────────────────────────────────────────

    def test_a_job_someone_holds_answers_409(self):
        first = self._job()
        self.me.post(inspect(first.pk))
        self.assertEqual(self.other.post(inspect(first.pk)).status_code, 409)

    def test_a_job_out_of_turn_answers_409(self):
        self._job(promise_in_hours=1)
        second = self._job(promise_in_hours=2)
        self.assertEqual(self.me.post(inspect(second.pk)).status_code, 409)

    def test_clearing_frees_the_claim_and_puts_the_job_in_press(self):
        first = self._job()
        self.me.post(inspect(first.pk))

        # Clearing now needs the two signed checks, as the new modal sends.
        cleared = self.me.post(verify(first.pk), {'signed_checks': ['TEXT', 'EDGES']}, format='json')
        self.assertEqual(cleared.status_code, 200, cleared.data)
        first.refresh_from_db()
        self.assertIsNone(first.inspecting_by)
        self.assertEqual(first.work_state, 'IN_PRODUCTION')

    def test_closing_the_workspace_frees_the_claim(self):
        first = self._job()
        self.me.post(inspect(first.pk))

        self.assertEqual(self.me.post(release(first.pk)).status_code, 200)
        first.refresh_from_db()
        self.assertIsNone(first.inspecting_by)

    # ── The board ────────────────────────────────────────────────

    def test_the_board_has_a_ready_column(self):
        done = self._job(
            intake_channel='WALK_IN', work_state='DONE',
            handover_state='AWAITING_COLLECTION',
        )
        board = self.me.get(BOARD).json()
        self.assertIn(done.pk, [r['id'] for r in board['columns']['READY']])

    def test_the_board_flags_a_late_job(self):
        late = self._job(
            promise_in_hours=-1,
            intake_channel='WALK_IN', work_state='IN_PRODUCTION',
        )
        board = self.me.get(BOARD).json()
        row = next(
            r for r in board['columns']['IN_PRODUCTION'] if r['id'] == late.pk
        )
        self.assertTrue(row['late'])
        self.assertFalse(row['at_risk'])

    # ── Moving work on ───────────────────────────────────────────

    def test_the_coordinator_can_move_work_on(self):
        """
        The finance scope does not know the coordinator, so every move
        answered "Job not found" until jobs got their own scope.
        """
        job = self._job(intake_channel='WALK_IN', work_state='IN_PRODUCTION')

        response = self.me.post(
            f'/api/v1/jobs/{job.pk}/move/',
            {'axis': 'WORK', 'to_state': 'FINISHING'}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.work_state, 'FINISHING')

    def test_the_coordinator_can_halt_and_resume(self):
        job = self._job(intake_channel='WALK_IN', work_state='IN_PRODUCTION')

        halted = self.me.post(
            f'/api/v1/jobs/{job.pk}/halt/',
            {'reason': 'MACHINE_BREAKDOWN'}, format='json',
        )
        resumed = self.me.post(f'/api/v1/jobs/{job.pk}/resume/')

        # 201: a halt is a record created, not just a move.
        self.assertEqual(halted.status_code, 201)
        self.assertEqual(resumed.status_code, 200)

    def test_the_coordinator_still_cannot_touch_money(self):
        """
        Seeing the branch's jobs is not the same as owning their money.
        The engine keeps the payment axis for the cashier.
        """
        job = self._job(
            intake_channel='WALK_IN', work_state='IN_PRODUCTION',
            payment_state='DEPOSIT_PAID',
        )

        response = self.me.post(
            f'/api/v1/jobs/{job.pk}/move/',
            {'axis': 'PAYMENT', 'to_state': 'SETTLED'}, format='json',
        )

        self.assertNotEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.payment_state, 'DEPOSIT_PAID')