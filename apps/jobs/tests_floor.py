"""
The floor through the coordinator's API: each machine with its line-up,
moving a job on, moving a job to another machine, and who may do it.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.jobs.models import Job, JobLineItem, JobStep, Service
from apps.jobs.status_engine import JobStatusEngine
from apps.jobs.tests import JobsFixtureMixin
from apps.production.models import Machine, MachineType, ServiceStation, Station

FLOOR = '/api/v1/jobs/coordinator/floor/'


def done(step):
    return f'/api/v1/jobs/steps/{step.pk}/done/'


def move(step):
    return f'/api/v1/jobs/steps/{step.pk}/move/'


class FloorApiTests(JobsFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.print_st = Station.objects.create(code='PRINT', name='Printing', sequence=1)
        cls.lam_st   = Station.objects.create(code='LAMINATE', name='Laminating', sequence=3)
        cls.fin_st   = Station.objects.create(code='FINISH', name='Hand finishing', sequence=5)

        cls.large = MachineType.objects.create(
            code='LARGE_FORMAT', name='Large format printer', station=cls.print_st,
        )
        cls.laminator = MachineType.objects.create(
            code='LAMINATOR', name='Laminator', station=cls.lam_st,
        )
        cls.six = Machine.objects.create(
            branch=cls.branch, machine_type=cls.large, name='6ft', max_width_mm=1829,
        )
        cls.ten = Machine.objects.create(
            branch=cls.branch, machine_type=cls.large, name='10ft', max_width_mm=3048,
        )
        cls.lam = Machine.objects.create(
            branch=cls.branch, machine_type=cls.laminator, name='Laminator',
        )

        cls.banner = Service.objects.create(
            name='Floor Banner', code='FLRBNR', category='PRODUCTION',
            unit='PER_SHEET', requires_design=False,
            requires_file_upload=False, is_active=True,
        )
        ServiceStation.objects.create(
            service=cls.banner, station=cls.print_st, machine_type=cls.large,
            sequence=1, setup_minutes=Decimal('5'), minutes_per_unit=Decimal('10'),
        )
        ServiceStation.objects.create(
            service=cls.banner, station=cls.lam_st, machine_type=cls.laminator,
            sequence=2, setup_minutes=Decimal('2'), minutes_per_unit=Decimal('5'),
        )
        ServiceStation.objects.create(
            service=cls.banner, station=cls.fin_st, machine_type=None,
            sequence=3, setup_minutes=Decimal('0'), minutes_per_unit=Decimal('3'),
        )

    def setUp(self):
        quiet = patch('apps.core.broadcast.broadcast_invalidation')
        quiet.start()
        self.addCleanup(quiet.stop)

        self.me = APIClient()
        self.me.force_authenticate(user=self.coordinator)

    def _cleared(self, **specs):
        job = Job.objects.create(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PAID, title='Floor test',
            intake_by=None, estimated_cost=Decimal('100.00'),
            daily_sheet=self.sheet, intake_channel='ONLINE',
            payment_state='SETTLED', work_state='RECEIVED',
            handover_state='AWAITING_COLLECTION',
            estimated_ready_at=timezone.now() + timedelta(hours=3),
        )
        JobLineItem.objects.create(
            job=job, service=self.banner, quantity=1,
            specifications=specs or {'width_ft': '3', 'height_ft': '2'},
        )
        JobStatusEngine(job).verify(actor=self.coordinator)
        job.refresh_from_db()
        return job

    def _print_step(self, job):
        return job.steps.get(station=self.print_st)

    def _lane(self, data, part, name):
        return next(e for e in data[part] if e['machine']['name'] == name)['queue']

    # ── Reading the floor ────────────────────────────────────────

    def test_the_floor_shows_each_machine_with_its_line_up(self):
        on_six = self._cleared()
        on_ten = self._cleared()

        data = self.me.get(FLOOR).json()

        self.assertEqual([r['job'] for r in self._lane(data, 'press', '6ft')], [on_six.pk])
        self.assertEqual([r['job'] for r in self._lane(data, 'press', '10ft')], [on_ten.pk])
        self.assertEqual(self._lane(data, 'press', '6ft')[0]['state'], 'ACTIVE')
        names = [e['machine']['name'] for e in data['finishing']]
        self.assertIn('Laminator', names)
        self.assertIn('Cutting / finishing', names)

    def test_a_line_up_counts_the_time_ahead(self):
        Machine.objects.filter(pk=self.ten.pk).update(is_available=False)
        self._cleared()
        self._cleared()

        lane = self._lane(self.me.get(FLOOR).json(), 'press', '6ft')

        self.assertEqual([r['minutes_until_done'] for r in lane], [15, 30])

    # ── Moving on ────────────────────────────────────────────────

    def test_done_moves_the_job_to_its_next_machine(self):
        job = self._cleared()

        response = self.me.post(done(self._print_step(job)))

        self.assertEqual(response.status_code, 200)
        lam_lane = self._lane(self.me.get(FLOOR).json(), 'finishing', 'Laminator')
        self.assertEqual([r['job'] for r in lam_lane], [job.pk])

    # ── Moving between machines ──────────────────────────────────

    def test_a_waiting_job_can_move_to_a_machine_that_fits(self):
        Machine.objects.filter(pk=self.ten.pk).update(is_available=False)
        self._cleared()
        waiting = self._cleared()
        Machine.objects.filter(pk=self.ten.pk).update(is_available=True)

        response = self.me.post(move(self._print_step(waiting)), {'machine': self.ten.pk}, format='json')

        self.assertEqual(response.status_code, 200)
        step = self._print_step(waiting)
        self.assertEqual(step.machine, self.ten)
        self.assertEqual(step.state, JobStep.State.ACTIVE)

    def test_a_piece_too_wide_is_refused_for_the_6ft(self):
        Machine.objects.filter(pk__in=[self.six.pk, self.ten.pk]).update(is_available=False)
        big = self._cleared(width_ft='8', height_ft='7')
        Machine.objects.filter(pk=self.six.pk).update(is_available=True)

        response = self.me.post(move(self._print_step(big)), {'machine': self.six.pk}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self._print_step(big).machine)

    def test_the_job_on_a_working_machine_stays_put(self):
        job = self._cleared()

        response = self.me.post(move(self._print_step(job)), {'machine': self.ten.pk}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._print_step(job).machine, self.six)

    def test_a_cancelled_job_leaves_its_machine_and_the_next_moves_up(self):
        Machine.objects.filter(pk=self.ten.pk).update(is_available=False)
        cancelled = self._cleared()
        behind = self._cleared()
        Job.objects.filter(pk=cancelled.pk).update(status='CANCELLED')

        lane = self._lane(self.me.get(FLOOR).json(), 'press', '6ft')

        self.assertEqual([r['job'] for r in lane], [behind.pk])
        self.assertEqual(lane[0]['state'], 'ACTIVE')

    # ── Who may ──────────────────────────────────────────────────

    def test_a_cashier_cannot_move_work_on(self):
        job = self._cleared()
        cashier = APIClient()
        cashier.force_authenticate(user=self.cashier)

        response = cashier.post(done(self._print_step(job)))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._print_step(job).state, JobStep.State.ACTIVE)