"""
The final check: ordered against made, at each piece's last step.

A match makes the piece ready, and the job ready once every piece is.
Anything that differs goes back to its machine to be made again, and the
estimate grows by itself. A last step cannot be finished any other way.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.jobs.models import FinalCheck, Job, JobLineItem, JobStep, Service
from apps.jobs.services.steps import StepRefused, mark_done
from apps.jobs.status_engine import JobStatusEngine
from apps.jobs.tests import JobsFixtureMixin
from apps.production.models import Machine, MachineType, ServiceStation, Station


def check_url(step):
    return f'/api/v1/jobs/steps/{step.pk}/check/'


class FinalCheckTests(JobsFixtureMixin, TestCase):

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
            name='Check Banner', code='CHKBNR', category='PRODUCTION',
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

    def _at_the_bench(self):
        """A banner cleared, printed and laminated: on the bench for its last step."""
        job = Job.objects.create(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PAID, title='Check test',
            intake_by=None, estimated_cost=Decimal('100.00'),
            daily_sheet=self.sheet, intake_channel='ONLINE',
            payment_state='SETTLED', work_state='RECEIVED',
            handover_state='AWAITING_COLLECTION',
            estimated_ready_at=timezone.now() + timedelta(hours=3),
        )
        JobLineItem.objects.create(
            job=job, service=self.banner, quantity=1,
            specifications={'width_ft': '3', 'height_ft': '2', 'material': 'Flexy 440gsm'},
        )
        JobStatusEngine(job).verify(actor=self.coordinator)
        mark_done(job.steps.get(station=self.print_st).pk, self.branch, self.coordinator)
        mark_done(job.steps.get(station=self.lam_st).pk, self.branch, self.coordinator)
        job.refresh_from_db()
        return job

    def _bench(self, job):
        return job.steps.get(station=self.fin_st)

    # ── What it shows ────────────────────────────────────────────

    def test_the_check_lists_what_was_ordered(self):
        job = self._at_the_bench()
        rows = self.me.get(check_url(self._bench(job))).json()['rows']
        by_field = {r['field']: r['ordered'] for r in rows}
        self.assertEqual(by_field['size'], '3 × 2 ft')
        self.assertEqual(by_field['quantity'], '1')
        self.assertEqual(by_field['material'], 'Flexy 440gsm')

    # ── Passing ──────────────────────────────────────────────────

    def test_a_match_makes_the_job_ready(self):
        job = self._at_the_bench()

        response = self.me.post(check_url(self._bench(job)), {'made': {}}, format='json')

        self.assertEqual(response.json()['outcome'], 'PASSED')
        job.refresh_from_db()
        self.assertEqual(job.work_state, 'DONE')
        self.assertFalse(job.steps.exclude(state=JobStep.State.DONE).exists())
        self.assertEqual(FinalCheck.objects.get(job=job).outcome, FinalCheck.Outcome.PASSED)

    def test_matching_reads_as_the_floor_would(self):
        job = self._at_the_bench()
        response = self.me.post(
            check_url(self._bench(job)), {'made': {'size': '3X2 FT'}}, format='json',
        )
        self.assertEqual(response.json()['outcome'], 'PASSED')

    # ── Sending back ─────────────────────────────────────────────

    def test_a_mismatch_goes_back_to_its_machine(self):
        job = self._at_the_bench()
        printed_on = job.steps.get(station=self.print_st).machine

        response = self.me.post(
            check_url(self._bench(job)), {'made': {'size': '3 × 1.5 ft'}}, format='json',
        )

        self.assertEqual(response.json()['outcome'], 'SENT_BACK')
        job.refresh_from_db()
        self.assertNotEqual(job.work_state, 'DONE')

        reprint = job.steps.get(station=self.print_st)
        self.assertEqual(reprint.machine, printed_on)
        self.assertEqual(reprint.state, JobStep.State.ACTIVE)
        self.assertEqual(job.steps.get(station=self.lam_st).state, JobStep.State.WAITING)
        self.assertEqual(self._bench(job).state, JobStep.State.WAITING)

        record = FinalCheck.objects.get(job=job)
        self.assertEqual(record.outcome, FinalCheck.Outcome.SENT_BACK)
        size = next(r for r in record.rows if r['field'] == 'size')
        self.assertFalse(size['match'])

    def test_the_estimate_grows_when_it_goes_back(self):
        from apps.jobs.services.estimates import estimate
        job = self._at_the_bench()
        before = estimate(job).minutes_left

        self.me.post(check_url(self._bench(job)), {'made': {'size': '3 × 1.5 ft'}}, format='json')
        job.refresh_from_db()
        after = estimate(job).minutes_left

        # On the bench: 3 minutes, shown as 5. Back to print: 15 + 7 + 3.
        self.assertEqual(before, 5)
        self.assertEqual(after, 25)

    # ── Nothing skips it ─────────────────────────────────────────

    def test_the_last_step_cannot_be_finished_without_the_check(self):
        job = self._at_the_bench()
        with self.assertRaises(StepRefused):
            mark_done(self._bench(job).pk, self.branch, self.coordinator)

    def test_a_cashier_cannot_check(self):
        job = self._at_the_bench()
        cashier = APIClient()
        cashier.force_authenticate(user=self.cashier)
        response = cashier.post(check_url(self._bench(job)), {'made': {}}, format='json')
        self.assertEqual(response.status_code, 403)