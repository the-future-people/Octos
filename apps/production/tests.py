"""
Tests for station timing observation.

Nothing here has ever run against real data — Westland is entirely instant
work, which moves RECEIVED → DONE in a single step and leaves no gap to
measure. These tests are the only evidence the arithmetic is right.

What they exercise: a clean single-station observation, an apportioned one,
halted time being excluded, the weighting that favours clean observations,
and the rolling average.
"""

import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser, Role
from apps.customers.models import CustomerProfile
from apps.finance.models import DailySalesSheet
from apps.jobs.models import Job, JobLineItem, JobStatusLog, Service
from apps.organization.models import Branch
from apps.production.models import (
    Machine, MachineType, ServiceStation, Station, StationTiming,
)
from apps.production.services.timing_service import TimingService


class TimingFixtureMixin:

    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(
            name='Timing Test Branch', code='TMB',
            is_headquarters=False, is_regional_hq=False,
            address='1 Test Road',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30),
            closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )

        cls.role = Role.objects.create(
            name='FLOW_COORDINATOR', display_name='Flow Coordinator',
            is_constrained=False, scope='BRANCH',
        )
        cls.actor = CustomUser(
            employee_id='TMB-CRD-1',
            first_name='Test', last_name='Coordinator',
            email='coord@timing.local',
            employment_status='ACTIVE', is_active=True,
            branch=cls.branch, role=cls.role,
        )
        cls.actor.set_password('test-pass-123')
        cls.actor.save()

        # ── Stations ─────────────────────────────────────────────
        cls.print_st = Station.objects.create(code='PRINT', name='Printing', sequence=1)
        cls.lam_st   = Station.objects.create(code='LAMINATE', name='Laminating', sequence=3)
        cls.bind_st  = Station.objects.create(code='BIND', name='Binding', sequence=4)

        cls.press_type = MachineType.objects.create(
            code='DIGITAL_PRESS', name='Digital press', station=cls.print_st,
        )
        Machine.objects.create(
            branch=cls.branch, machine_type=cls.press_type, name='Test press',
        )

        # ── Services and their routes ────────────────────────────
        cls.printing = Service.objects.create(
            name='Test Printing', code='TMBPRN', category='PRODUCTION',
            unit='PER_SHEET', requires_design=False,
            requires_file_upload=False, is_active=True,
        )
        ServiceStation.objects.create(
            service=cls.printing, station=cls.print_st,
            machine_type=cls.press_type, sequence=1,
            setup_minutes=Decimal('2'), minutes_per_unit=Decimal('0.05'),
        )

        cls.lamination = Service.objects.create(
            name='Test Lamination', code='TMBLAM', category='PRODUCTION',
            unit='PER_SHEET', requires_design=False,
            requires_file_upload=False, is_active=True,
        )
        ServiceStation.objects.create(
            service=cls.lamination, station=cls.lam_st,
            sequence=1,
            setup_minutes=Decimal('1'), minutes_per_unit=Decimal('0.30'),
        )

        cls.binding = Service.objects.create(
            name='Test Binding', code='TMBBND', category='PRODUCTION',
            unit='PER_JOB', requires_design=False,
            requires_file_upload=False, is_active=True,
        )
        ServiceStation.objects.create(
            service=cls.binding, station=cls.bind_st,
            sequence=1,
            setup_minutes=Decimal('2'), minutes_per_unit=Decimal('2.50'),
        )

        cls.today = timezone.localdate()
        cls.sheet, _ = DailySalesSheet.objects.get_or_create(
            branch=cls.branch, date=cls.today,
            defaults={'status': DailySalesSheet.Status.OPEN},
        )

    # ── Helpers ──────────────────────────────────────────────────

    def _job(self, lines, work_state='DONE'):
        """A production job with the given (service, quantity, pages) lines."""
        job = Job.objects.create(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PENDING_PAYMENT, title='Timing test',
            intake_by=self.actor, estimated_cost=Decimal('100.00'),
            daily_sheet=self.sheet,
            payment_state='DEPOSIT_PAID', work_state=work_state,
            handover_state='AWAITING_COLLECTION',
        )
        for i, (service, quantity, pages) in enumerate(lines):
            JobLineItem.objects.create(
                job=job, service=service, quantity=quantity, pages=pages,
                unit_price=Decimal('1.00'), line_total=Decimal('10.00'),
                position=i,
            )
        return job

    def _log(self, job, to_status, at):
        """A work-axis transition at a controlled time."""
        return JobStatusLog.objects.create(
            job=job, axis='WORK', from_status='', to_status=to_status,
            actor=self.actor, transitioned_at=at,
        )

    @staticmethod
    def _at(hour, minute=0):
        return timezone.make_aware(
            datetime.datetime.combine(
                timezone.localdate(), datetime.time(hour, minute)
            )
        )


class PrintTimingTests(TimingFixtureMixin, TestCase):

    def test_clean_print_observation(self):
        """100 sheets in 10 minutes is 0.1 minutes a sheet."""
        job = self._job([(self.printing, 100, 1)])
        self._log(job, 'IN_PRODUCTION', self._at(9, 0))
        self._log(job, 'FINISHING',     self._at(9, 10))

        obs = TimingService._observe_job(job)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]['station'], 'PRINT')
        self.assertTrue(obs[0]['is_clean'])
        self.assertAlmostEqual(obs[0]['per_unit'], 0.1, places=4)

    def test_pages_multiply_units(self):
        """10 copies of a 10-page document is 100 sheets, not 10."""
        job = self._job([(self.printing, 10, 10)])
        self._log(job, 'IN_PRODUCTION', self._at(9, 0))
        self._log(job, 'FINISHING',     self._at(9, 10))

        obs = TimingService._observe_job(job)
        self.assertAlmostEqual(obs[0]['per_unit'], 0.1, places=4)

    def test_halted_time_is_excluded(self):
        """
        A job stopped an hour mid-print did not take an hour to print.
        Counting it would teach the system that printing is slow when the
        truth is that a machine broke.
        """
        from apps.jobs.models import JobHalt

        job = self._job([(self.printing, 100, 1)])
        self._log(job, 'IN_PRODUCTION', self._at(9, 0))
        self._log(job, 'FINISHING',     self._at(10, 10))

        halt = JobHalt.objects.create(
            job=job, reason='MACHINE_BREAKDOWN',
            work_state_at_halt='IN_PRODUCTION', halted_by=self.actor,
        )
        JobHalt.objects.filter(pk=halt.pk).update(halted_at=self._at(9, 5))
        halt.refresh_from_db()
        halt.resumed_at = self._at(10, 5)
        halt.resumed_by = self.actor
        halt.save(update_fields=['resumed_at', 'resumed_by', 'updated_at'])

        obs = TimingService._observe_job(job)
        # 70 minutes elapsed, 60 of them halted, so 10 minutes of work.
        self.assertAlmostEqual(obs[0]['per_unit'], 0.1, places=4)

    def test_no_observation_without_a_gap(self):
        """An instant job goes RECEIVED to DONE and has nothing to measure."""
        job = self._job([(self.printing, 100, 1)])
        self._log(job, 'DONE', self._at(9, 0))
        self.assertEqual(TimingService._observe_job(job), [])


class FinishingTimingTests(TimingFixtureMixin, TestCase):

    def test_single_finishing_station_is_clean(self):
        """One station involved means the whole gap belongs to it."""
        job = self._job([(self.lamination, 20, 1)])
        self._log(job, 'FINISHING',     self._at(11, 0))
        self._log(job, 'QUALITY_CHECK', self._at(11, 10))

        obs = TimingService._observe_job(job)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]['station'], 'LAMINATE')
        self.assertTrue(obs[0]['is_clean'])
        self.assertAlmostEqual(obs[0]['per_unit'], 0.5, places=4)

    def test_two_stations_are_apportioned_and_marked(self):
        """
        Laminating and binding in one gap cannot be separated, so the time
        is split by seed estimate — a guess resting on a guess, and marked
        as such so it is weighted below a clean observation.
        """
        job = self._job([(self.lamination, 10, 1), (self.binding, 2, 1)])
        self._log(job, 'FINISHING',     self._at(11, 0))
        self._log(job, 'QUALITY_CHECK', self._at(11, 20))

        obs = {o['station']: o for o in TimingService._observe_job(job)}
        self.assertEqual(set(obs), {'LAMINATE', 'BIND'})
        self.assertFalse(obs['LAMINATE']['is_clean'])
        self.assertFalse(obs['BIND']['is_clean'])

        # Seed estimates: lamination 1 + 0.30×10 = 4; binding 2 + 2.50×2 = 7.
        # Of 20 minutes, lamination takes 4/11 and binding 7/11.
        self.assertAlmostEqual(obs['LAMINATE']['per_unit'], (20 * 4 / 11) / 10, places=3)
        self.assertAlmostEqual(obs['BIND']['per_unit'],     (20 * 7 / 11) / 2,  places=3)


class TimingApplicationTests(TimingFixtureMixin, TestCase):

    def test_first_observation_creates_a_slot(self):
        TimingService._apply({
            'branch': self.branch, 'station': 'PRINT',
            'at': self._at(9, 0), 'per_unit': 0.1, 'is_clean': True,
        })
        timing = StationTiming.objects.get(branch=self.branch, station=self.print_st)
        self.assertAlmostEqual(float(timing.observed_minutes_per_unit), 0.1, places=4)
        self.assertEqual(timing.sample_count, 3)   # clean weight

    def test_clean_observations_outweigh_apportioned(self):
        """
        An apportioned figure is right about the whole and unreliable about
        the parts, so it must not drag a well-observed slot as hard as a
        clean one.
        """
        common = {'branch': self.branch, 'station': 'PRINT', 'at': self._at(9, 0)}
        TimingService._apply({**common, 'per_unit': 0.10, 'is_clean': True})
        TimingService._apply({**common, 'per_unit': 0.50, 'is_clean': False})

        timing = StationTiming.objects.get(branch=self.branch, station=self.print_st)
        # (0.10×3 + 0.50×1) / 4 = 0.20
        self.assertAlmostEqual(float(timing.observed_minutes_per_unit), 0.20, places=4)
        self.assertEqual(timing.sample_count, 4)

    def test_slots_are_separated_by_hour_and_day(self):
        """A busy afternoon is not a quiet morning."""
        common = {'branch': self.branch, 'station': 'PRINT', 'is_clean': True}
        TimingService._apply({**common, 'at': self._at(9, 0),  'per_unit': 0.1})
        TimingService._apply({**common, 'at': self._at(16, 0), 'per_unit': 0.4})

        self.assertEqual(
            StationTiming.objects.filter(branch=self.branch).count(), 2
        )

    def test_one_strange_job_cannot_swing_a_settled_slot(self):
        common = {'branch': self.branch, 'station': 'PRINT',
                  'at': self._at(9, 0), 'is_clean': True}
        for _ in range(10):
            TimingService._apply({**common, 'per_unit': 0.10})
        TimingService._apply({**common, 'per_unit': 5.00})

        timing = StationTiming.objects.get(branch=self.branch, station=self.print_st)
        self.assertLess(float(timing.observed_minutes_per_unit), 0.6)