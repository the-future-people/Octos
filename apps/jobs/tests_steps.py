"""
A job's steps across the floor.

Built on a small copy of Westland: two large-format printers of
different widths, a laminator, and a hand-finishing station with no
machine at all. A banner prints, is laminated, then finished by hand.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.jobs.models import Job, JobLineItem, JobStep, Service
from apps.jobs.services.steps import build_steps, fill, queue
from apps.jobs.tests import JobsFixtureMixin
from apps.production.models import Machine, MachineType, ServiceStation, Station


class StepTests(JobsFixtureMixin, TestCase):

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

        # Created in this order so that, all else equal, the 6ft is first.
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
            name='Test Banner', code='TSTBNR', category='PRODUCTION',
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

    def _job(self, promise_in_hours=2, **specs):
        job = Job.objects.create(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PAID, title='Step test',
            intake_by=None, estimated_cost=Decimal('100.00'),
            daily_sheet=self.sheet, intake_channel='ONLINE',
            payment_state='SETTLED', work_state='IN_PRODUCTION',
            handover_state='AWAITING_COLLECTION',
            estimated_ready_at=timezone.now() + timedelta(hours=promise_in_hours),
        )
        JobLineItem.objects.create(
            job=job, service=self.banner, quantity=1,
            specifications=specs or {'width_ft': '3', 'height_ft': '2'},
        )
        return job

    def _print_step(self, job):
        return job.steps.get(station=self.print_st)

    # ── Choosing machines ────────────────────────────────────────

    def test_a_piece_too_wide_for_the_6ft_goes_to_the_10ft(self):
        # 8 × 7 ft: the short side, 7 ft, is wider than the 6ft can take.
        job = self._job(width_ft='8', height_ft='7')
        build_steps(job)
        self.assertEqual(self._print_step(job).machine, self.ten)

    def test_the_machine_with_less_waiting_wins(self):
        first = self._job()
        build_steps(first)
        second = self._job()
        build_steps(second)

        self.assertEqual(self._print_step(first).machine, self.six)
        self.assertEqual(self._print_step(second).machine, self.ten)

    def test_a_machine_that_is_down_is_never_chosen(self):
        Machine.objects.filter(pk=self.six.pk).update(is_available=False)
        job = self._job()
        build_steps(job)
        self.assertEqual(self._print_step(job).machine, self.ten)

    def test_when_nothing_fits_the_step_waits_for_the_coordinator(self):
        Machine.objects.filter(pk__in=[self.six.pk, self.ten.pk]).update(is_available=False)
        job = self._job()
        build_steps(job)

        step = self._print_step(job)
        self.assertIsNone(step.machine)
        self.assertEqual(step.state, JobStep.State.WAITING)

    def test_hand_finishing_goes_to_the_bench(self):
        job = self._job()
        build_steps(job)
        self.assertIsNone(job.steps.get(station=self.fin_st).machine)

    # ── Queues ───────────────────────────────────────────────────

    def test_the_front_of_a_queue_starts_by_itself(self):
        Machine.objects.filter(pk=self.ten.pk).update(is_available=False)
        first = self._job()
        build_steps(first)
        second = self._job()
        build_steps(second)

        on_it = self._print_step(first)
        self.assertEqual(on_it.state, JobStep.State.ACTIVE)
        self.assertIsNotNone(on_it.reached_at)
        self.assertEqual(self._print_step(second).state, JobStep.State.WAITING)

    def test_the_job_on_the_machine_stays_at_the_front(self):
        """A sooner promise waits its turn; it does not knock a job off the machine."""
        Machine.objects.filter(pk=self.ten.pk).update(is_available=False)
        running = self._job(promise_in_hours=5)
        build_steps(running)
        urgent = self._job(promise_in_hours=1)
        build_steps(urgent)

        line_up = [s.job_id for s in queue(self.branch, machine=self.six)]
        self.assertEqual(line_up, [running.pk, urgent.pk])

    def test_waiting_jobs_line_up_by_promise(self):
        Machine.objects.filter(pk=self.ten.pk).update(is_available=False)
        running = self._job(promise_in_hours=1)
        build_steps(running)
        later = self._job(promise_in_hours=6)
        build_steps(later)
        sooner = self._job(promise_in_hours=3)
        build_steps(sooner)

        line_up = [s.job_id for s in queue(self.branch, machine=self.six)]
        self.assertEqual(line_up, [running.pk, sooner.pk, later.pk])

    def test_a_later_step_does_not_queue_while_printing(self):
        """A banner still printing is not waiting at the laminator."""
        job = self._job()
        build_steps(job)
        self.assertEqual(list(queue(self.branch, machine=self.lam)), [])

    def test_the_bench_takes_a_line_once_its_machines_are_done(self):
        job = self._job()
        build_steps(job)
        job.steps.exclude(station=self.fin_st).update(state=JobStep.State.DONE)

        fill(self.branch, station=self.fin_st)

        self.assertEqual(
            job.steps.get(station=self.fin_st).state, JobStep.State.ACTIVE,
        )

    # ── Safety ───────────────────────────────────────────────────

    def test_building_twice_makes_no_duplicates(self):
        job = self._job()
        build_steps(job)
        build_steps(job)
        self.assertEqual(job.steps.count(), 3)

    # ── Moving on ────────────────────────────────────────────────

    def _cleared(self, **kwargs):
        """A job brought in through inspection, as the floor sees it."""
        from apps.jobs.status_engine import JobStatusEngine
        job = self._job(**kwargs)
        Job.objects.filter(pk=job.pk).update(work_state='RECEIVED')
        job.refresh_from_db()
        JobStatusEngine(job).verify(actor=self.coordinator)
        job.refresh_from_db()
        return job

    def test_clearing_builds_the_steps_and_starts_printing(self):
        job = self._cleared()
        self.assertEqual(job.steps.count(), 3)
        self.assertEqual(self._print_step(job).state, JobStep.State.ACTIVE)
        self.assertEqual(job.work_state, 'IN_PRODUCTION')

    def test_printing_done_sends_it_to_the_laminator(self):
        from apps.jobs.services.steps import mark_done
        job = self._cleared()

        mark_done(self._print_step(job).pk, self.branch, self.coordinator)

        printed = self._print_step(job)
        self.assertEqual(printed.state, JobStep.State.DONE)
        self.assertIsNotNone(printed.done_at)
        self.assertEqual(printed.done_by, self.coordinator)
        self.assertEqual(
            job.steps.get(station=self.lam_st).state, JobStep.State.ACTIVE,
        )
        job.refresh_from_db()
        self.assertEqual(job.work_state, 'FINISHING')

    def test_the_next_job_on_the_machine_moves_up(self):
        from apps.jobs.services.steps import mark_done
        Machine.objects.filter(pk=self.ten.pk).update(is_available=False)
        first = self._cleared()
        second = self._cleared()
        self.assertEqual(self._print_step(second).state, JobStep.State.WAITING)

        mark_done(self._print_step(first).pk, self.branch, self.coordinator)

        self.assertEqual(self._print_step(second).state, JobStep.State.ACTIVE)

    def test_only_the_job_on_the_machine_can_be_marked_done(self):
        from apps.jobs.services.steps import StepRefused, mark_done
        Machine.objects.filter(pk=self.ten.pk).update(is_available=False)
        self._cleared()
        waiting = self._cleared()

        with self.assertRaises(StepRefused):
            mark_done(self._print_step(waiting).pk, self.branch, self.coordinator)

    def test_finishing_waits_for_every_line_to_print(self):
        from apps.jobs.services.steps import mark_done
        job = self._job()
        JobLineItem.objects.create(
            job=job, service=self.banner, quantity=1,
            specifications={'width_ft': '2', 'height_ft': '2'},
        )
        Job.objects.filter(pk=job.pk).update(work_state='RECEIVED')
        job.refresh_from_db()
        from apps.jobs.status_engine import JobStatusEngine
        JobStatusEngine(job).verify(actor=self.coordinator)

        first, second = job.steps.filter(station=self.print_st).order_by('pk')
        mark_done(first.pk, self.branch, self.coordinator)
        job.refresh_from_db()
        self.assertEqual(job.work_state, 'IN_PRODUCTION')

        mark_done(second.pk, self.branch, self.coordinator)
        job.refresh_from_db()
        self.assertEqual(job.work_state, 'FINISHING')

    def test_a_halted_job_cannot_be_moved_on(self):
        from apps.jobs.services.steps import StepRefused, mark_done
        from apps.jobs.status_engine import JobStatusEngine
        job = self._cleared()
        JobStatusEngine(job).halt(reason='MACHINE_BREAKDOWN', actor=self.coordinator)

        with self.assertRaises(StepRefused):
            mark_done(self._print_step(job).pk, self.branch, self.coordinator)

    # ── A machine going down ─────────────────────────────────────

    def _down(self, machine):
        from apps.production.services.machine_service import MachineService
        return MachineService.mark_down(
            Machine.objects.get(pk=machine.pk), 'MECHANICAL', self.coordinator,
        )

    def _halted(self, job):
        return job.halts.filter(resumed_at__isnull=True).exists()

    def test_a_machine_down_halts_only_the_job_on_it(self):
        on_six = self._cleared()
        on_ten = self._cleared()
        self.assertEqual(self._print_step(on_ten).machine, self.ten)

        self._down(self.six)

        self.assertTrue(self._halted(on_six))
        self.assertFalse(self._halted(on_ten))

    def test_jobs_queued_behind_move_to_a_machine_that_fits(self):
        Machine.objects.filter(pk=self.ten.pk).update(is_available=False)
        self._cleared()
        queued = self._cleared()
        self.assertEqual(self._print_step(queued).machine, self.six)
        Machine.objects.filter(pk=self.ten.pk).update(is_available=True)

        result = self._down(self.six)

        moved = self._print_step(queued)
        self.assertEqual(moved.machine, self.ten)
        self.assertEqual(moved.state, JobStep.State.ACTIVE)
        self.assertFalse(self._halted(queued))
        self.assertEqual(result['moved_count'], 1)

    def test_with_nowhere_to_go_they_wait_for_it_without_halting(self):
        Machine.objects.filter(pk=self.ten.pk).update(is_available=False)
        self._cleared()
        queued = self._cleared()

        self._down(self.six)

        waiting = self._print_step(queued)
        self.assertEqual(waiting.machine, self.six)
        self.assertEqual(waiting.state, JobStep.State.WAITING)
        self.assertFalse(self._halted(queued))

    def test_back_up_resumes_its_job_and_carries_on(self):
        from apps.production.services.machine_service import MachineService
        job = self._cleared()
        self._down(self.six)
        self.assertTrue(self._halted(job))

        MachineService.mark_up(Machine.objects.get(pk=self.six.pk), self.coordinator)

        self.assertFalse(self._halted(job))
        self.assertEqual(self._print_step(job).state, JobStep.State.ACTIVE)

    def test_each_step_knows_how_long_its_work_takes(self):
        job = self._job()
        build_steps(job)
        # Print: 5 setup + 10 a unit, one unit.
        self.assertEqual(self._print_step(job).expected_minutes, Decimal('15.0'))