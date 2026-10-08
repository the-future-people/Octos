import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.jobs.models import Job, JobLineItem, Service
from apps.organization.models import Branch
from apps.production.models import (
    BranchStation, MachineType, ServiceStation, Station,
)


class ReadyEstimateTests(TestCase):
    """
    When a job will be ready.

    Three things decide it: how long the work takes, how much is ahead
    of it, and the fact that a branch is shut overnight. The third is
    the one that catches people out — a job accepted at six with three
    hours of work in it is not ready at nine, because the branch closed
    at half seven.
    """

    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(
            name='Estimate Branch', code='ESB',
            is_headquarters=False, is_regional_hq=False,
            address='1 Estimate Road',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30),
            closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )

        cls.print_st = Station.objects.create(code='PRINT', name='Printing', sequence=1)
        cls.cut_st = Station.objects.create(code='CUT', name='Cutting', sequence=2)
        cls.finish_st = Station.objects.create(code='FINISH', name='Finishing', sequence=5)

        cls.large = MachineType.objects.create(
            code='LARGE_FORMAT', name='Large format printer',
            station=cls.print_st, max_width_mm=3200,
        )

        cls.flexy = Service.objects.create(
            name='Estimate Flexy', code='ESFLEXY',
            category='PRODUCTION', unit='PER_SQFT',
            requires_design=False, requires_file_upload=True, is_active=True,
        )
        # 12 min setup + 0.143/sq ft printing, 10 min cutting,
        # 5 min + 0.25/sq ft finishing.
        ServiceStation.objects.create(
            service=cls.flexy, station=cls.print_st, machine_type=cls.large,
            sequence=1, setup_minutes=Decimal('12'), minutes_per_unit=Decimal('0.143'),
        )
        ServiceStation.objects.create(
            service=cls.flexy, station=cls.cut_st, machine_type=None,
            sequence=2, setup_minutes=Decimal('10'), minutes_per_unit=Decimal('0'),
        )
        ServiceStation.objects.create(
            service=cls.flexy, station=cls.finish_st, machine_type=None,
            sequence=3, setup_minutes=Decimal('5'), minutes_per_unit=Decimal('0.25'),
        )

    def _somebody(self):
        """Someone to attribute a halt to. The model requires it."""
        from apps.accounts.models import CustomUser, Role
        role, _ = Role.objects.get_or_create(
            name='EST_COORDINATOR',
            defaults={'display_name': 'Coordinator', 'scope': 'BRANCH'},
        )
        user = CustomUser(
            employee_id='EST-001', first_name='Est', last_name='Coordinator',
            email='est@test.local', employment_status='ACTIVE',
            is_active=True, branch=self.branch, role=role,
        )
        user.set_password('test-pass-123')
        user.save()
        return user

    def _at(self, hour, minute=0, day=None):
        """A moment on a trading day — Monday unless told otherwise."""
        base = day or datetime.date(2026, 10, 5)  # a Monday
        naive = datetime.datetime.combine(base, datetime.time(hour, minute))
        return timezone.make_aware(naive)

    def _job(self, sqft=18, quantity=1, **overrides):
        defaults = dict(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PENDING_PAYMENT, title='Estimate job',
            estimated_cost=Decimal('100.00'),
            payment_state='DEPOSIT_PAID', work_state='RECEIVED',
            handover_state='AWAITING_COLLECTION',
        )
        defaults.update(overrides)
        job = Job.objects.create(**defaults)
        # The dimensions have to match the area asked for, or the engine
        # reads them and the sqft argument means nothing.
        side = Decimal(str(sqft * 144)).sqrt()
        JobLineItem.objects.create(
            job=job, service=self.flexy,
            quantity=sqft, pages=quantity,
            unit_price=Decimal('3.25'), line_total=Decimal('58.50'),
            specifications={
                'width_in': float(side), 'height_in': float(side),
            },
        )
        return job

    # ── The work itself ────────────────────────────────────────────

    def test_the_work_is_the_sum_of_its_stations(self):
        """
        An 18 sq ft banner: 12 + 2.6 printing, 10 cutting, 5 + 4.5
        finishing. About 34 minutes.
        """
        from apps.production.estimate import work_minutes

        minutes = work_minutes(self._job(sqft=18))
        self.assertAlmostEqual(minutes, 34.1, delta=0.5)

    def test_a_bigger_banner_takes_longer_only_where_size_matters(self):
        """
        Cutting is ten minutes whether it is six feet or sixteen. Only
        printing and finishing grow.
        """
        small = work_minutes_for(self, 18)
        large = work_minutes_for(self, 175)
        # 157 extra sq ft at 0.393 min/sq ft across print and finish.
        self.assertAlmostEqual(large - small, 61.7, delta=1.0)

    def test_quantity_multiplies_the_work(self):
        from apps.production.estimate import work_minutes

        one = work_minutes(self._job(sqft=18, quantity=1))
        three = work_minutes(self._job(sqft=18, quantity=3))
        self.assertGreater(three, one * 2)

    def test_a_service_with_no_route_is_not_guessed_at(self):
        """
        A service nobody has mapped through the floor has no honest
        estimate. Returning zero would say it is ready immediately.
        """
        from apps.production.estimate import work_minutes

        unmapped = Service.objects.create(
            name='Unmapped', code='ESUNMAP', category='PRODUCTION',
            unit='PER_PIECE', is_active=True,
        )
        job = self._job()
        job.line_items.update(service=unmapped)
        self.assertIsNone(work_minutes(job))

    # ── People ─────────────────────────────────────────────────────

    def test_two_people_at_a_station_halve_its_share_of_the_queue(self):
        """
        Capacity is people. Two at the printer means two banners print
        at once; the queue clears twice as fast.
        """
        from apps.production.estimate import queue_minutes

        for _ in range(4):
            self._job(sqft=18, work_state='RECEIVED')

        one = queue_minutes(self.branch)
        BranchStation.objects.create(
            branch=self.branch, station=self.print_st, people=2,
        )
        two = queue_minutes(self.branch)

        self.assertLess(two, one)

    # ── The queue ──────────────────────────────────────────────────

    def test_work_already_on_the_floor_is_counted(self):
        from apps.production.estimate import queue_minutes

        self.assertEqual(queue_minutes(self.branch), 0)
        self._job(sqft=18)
        self.assertGreater(queue_minutes(self.branch), 30)

    def test_a_halted_job_is_not_in_the_queue(self):
        """Nobody is working on it, so it is not in anyone's way."""
        from apps.jobs.models import JobHalt
        from apps.production.estimate import queue_minutes

        job = self._job(sqft=18, work_state='IN_PRODUCTION')
        before = queue_minutes(self.branch)

        JobHalt.objects.create(
            job=job, reason='MATERIALS_OUT', work_state_at_halt='IN_PRODUCTION',
            halted_by=self._somebody(),
        )
        self.assertLess(queue_minutes(self.branch), before)

    def test_a_finished_job_is_not_in_the_queue(self):
        from apps.production.estimate import queue_minutes

        self._job(sqft=18, work_state='DONE')
        self.assertEqual(queue_minutes(self.branch), 0)

    # ── The clock ──────────────────────────────────────────────────

    def test_an_hour_of_work_at_nine_is_ready_at_ten(self):
        from apps.production.estimate import ready_at

        when = ready_at(self.branch, 60, start=self._at(9, 0))
        self.assertEqual(when.hour, 10)
        self.assertEqual(when.date(), datetime.date(2026, 10, 5))

    def test_work_that_does_not_fit_today_finishes_tomorrow(self):
        """
        Three hours of work accepted at six is not ready at nine. The
        branch shuts at half seven and the rest is done in the morning.
        """
        from apps.production.estimate import ready_at

        when = ready_at(self.branch, 180, start=self._at(18, 0))
        self.assertEqual(when.date(), datetime.date(2026, 10, 6))
        # 90 minutes done today, 90 left from 07:30.
        self.assertEqual((when.hour, when.minute), (9, 0))

    def test_work_accepted_after_closing_starts_in_the_morning(self):
        from apps.production.estimate import ready_at

        when = ready_at(self.branch, 60, start=self._at(21, 0))
        self.assertEqual(when.date(), datetime.date(2026, 10, 6))
        self.assertEqual((when.hour, when.minute), (8, 30))

    def test_sunday_is_skipped(self):
        """The branch does not trade on Sunday, so nothing is made."""
        from apps.production.estimate import ready_at

        saturday = datetime.date(2026, 10, 10)
        when = ready_at(self.branch, 600, start=self._at(18, 0, day=saturday))
        # 90 minutes on Saturday, nothing on Sunday, the rest on Monday.
        self.assertEqual(when.date(), datetime.date(2026, 10, 12))

    def test_work_accepted_before_opening_starts_at_opening(self):
        from apps.production.estimate import ready_at

        when = ready_at(self.branch, 30, start=self._at(6, 0))
        self.assertEqual((when.hour, when.minute), (8, 0))


def work_minutes_for(case, sqft):
    from apps.production.estimate import work_minutes
    return work_minutes(case._job(sqft=sqft))