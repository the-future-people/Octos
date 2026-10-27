"""
The operator's machine: Start, slack order, and every line ending at the bench.

A small floor: one DTF printer with an operator assigned, and the hand-
finishing bench. Transfers are printed and nothing more, so their route
ends on the machine and the bench step is added for them.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.jobs.models import Job, JobLineItem, JobStep, Service
from apps.jobs.services.steps import StepRefused, build_steps, mark_done, queue, start_step
from apps.jobs.tests import JobsFixtureMixin
from apps.production.models import Machine, MachineOperator, MachineType, ServiceStation, Station


class OperatorStepTests(JobsFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.print_st = Station.objects.create(code='PRINT', name='Printing', sequence=1)
        cls.fin_st   = Station.objects.create(code='FINISH', name='Hand finishing', sequence=5)

        cls.dtf_type = MachineType.objects.create(
            code='DTF', name='DTF printer', station=cls.print_st,
        )
        cls.dtf = Machine.objects.create(
            branch=cls.branch, machine_type=cls.dtf_type, name='DTF printer',
        )

        cls.transfers = Service.objects.create(
            name='Test Transfers', code='TSTDTF', category='PRODUCTION',
            unit='PER_PIECE', requires_design=False,
            requires_file_upload=False, is_active=True,
        )
        # Print only: 5 minutes setup, 10 a piece.
        ServiceStation.objects.create(
            service=cls.transfers, station=cls.print_st, machine_type=cls.dtf_type,
            sequence=1, setup_minutes=Decimal('5'), minutes_per_unit=Decimal('10'),
        )

        cls.operator = cls.attendant
        cls.assignment = MachineOperator.objects.create(operator=cls.operator, machine=cls.dtf)

    def _job(self, promise_in_hours=2, quantity=1):
        job = Job.objects.create(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PAID, title='Operator test',
            intake_by=None, estimated_cost=Decimal('100.00'),
            daily_sheet=self.sheet, intake_channel='ONLINE',
            payment_state='SETTLED', work_state='IN_PRODUCTION',
            handover_state='AWAITING_COLLECTION',
            estimated_ready_at=timezone.now() + timedelta(hours=promise_in_hours),
        )
        JobLineItem.objects.create(job=job, service=self.transfers, quantity=quantity)
        return job

    def _print(self, job):
        return job.steps.get(station=self.print_st)

    # ── The bench ────────────────────────────────────────────────

    def test_a_line_ending_on_a_machine_ends_at_the_bench(self):
        job = self._job()
        build_steps(job)
        steps = list(job.steps.order_by('sequence'))
        self.assertEqual([s.station_id for s in steps], [self.print_st.pk, self.fin_st.pk])
        self.assertTrue(steps[-1].by_hand)
        self.assertIsNone(steps[-1].machine)

    # ── Staffed and unstaffed ────────────────────────────────────

    def test_a_staffed_machine_waits_for_start(self):
        job = self._job()
        build_steps(job)
        step = self._print(job)
        self.assertEqual(step.state, JobStep.State.WAITING)
        self.assertIsNotNone(step.reached_at)

    def test_an_unstaffed_machine_still_starts_by_itself(self):
        MachineOperator.objects.filter(pk=self.assignment.pk).update(active_until=timezone.now())
        job = self._job()
        build_steps(job)
        self.assertEqual(self._print(job).state, JobStep.State.ACTIVE)

    # ── Slack ────────────────────────────────────────────────────

    def test_the_queue_is_ordered_by_slack_not_promise(self):
        # Promised later but 205 minutes of work: it must start first.
        soon_small = self._job(promise_in_hours=3, quantity=1)
        later_big  = self._job(promise_in_hours=4, quantity=20)
        build_steps(soon_small)
        build_steps(later_big)
        order = [s.job_id for s in queue(self.branch, machine=self.dtf)]
        self.assertEqual(order, [later_big.pk, soon_small.pk])

    # ── Start ────────────────────────────────────────────────────

    def test_start_puts_the_front_on_the_machine(self):
        job = self._job()
        build_steps(job)
        start_step(self._print(job).pk, self.branch, self.operator)

        step = self._print(job)
        self.assertEqual(step.state, JobStep.State.ACTIVE)
        self.assertEqual(step.started_by, self.operator)
        self.assertIsNotNone(step.started_at)
        job.refresh_from_db()
        self.assertIsNotNone(job.work_started_at)

    def test_only_an_assigned_operator_can_start(self):
        job = self._job()
        build_steps(job)
        with self.assertRaises(StepRefused) as ctx:
            start_step(self._print(job).pk, self.branch, self.coordinator)
        self.assertIn('not assigned', str(ctx.exception))

    def test_only_the_front_of_the_queue_can_start(self):
        front = self._job(promise_in_hours=1)
        behind = self._job(promise_in_hours=5)
        build_steps(front)
        build_steps(behind)
        with self.assertRaises(StepRefused) as ctx:
            start_step(self._print(behind).pk, self.branch, self.operator)
        self.assertIn('front of the queue', str(ctx.exception))

    def test_nothing_starts_while_a_job_is_on_the_machine(self):
        first = self._job(promise_in_hours=1)
        second = self._job(promise_in_hours=5)
        build_steps(first)
        build_steps(second)
        start_step(self._print(first).pk, self.branch, self.operator)
        with self.assertRaises(StepRefused) as ctx:
            start_step(self._print(second).pk, self.branch, self.operator)
        self.assertIn('still on', str(ctx.exception))

    # ── Done ─────────────────────────────────────────────────────

    def test_done_records_counts_frees_the_machine_and_the_next_waits(self):
        first = self._job(promise_in_hours=1, quantity=3)
        second = self._job(promise_in_hours=5)
        build_steps(first)
        build_steps(second)
        start_step(self._print(first).pk, self.branch, self.operator)

        mark_done(self._print(first).pk, self.branch, self.operator, made=3, spoilt=1)

        done = self._print(first)
        self.assertEqual(done.state, JobStep.State.DONE)
        self.assertEqual((done.quantity_made, done.quantity_spoilt), (3, 1))
        # The piece goes on to the bench, which starts by itself.
        self.assertEqual(first.steps.get(station=self.fin_st).state, JobStep.State.ACTIVE)
        # The next job on the machine waits for Start.
        nxt = self._print(second)
        self.assertEqual(nxt.state, JobStep.State.WAITING)
        self.assertIsNotNone(nxt.reached_at)

    def test_the_final_check_happens_at_the_bench(self):
        from apps.jobs.services.final_check import check
        job = self._job()
        build_steps(job)
        start_step(self._print(job).pk, self.branch, self.operator)
        mark_done(self._print(job).pk, self.branch, self.operator, made=1, spoilt=0)

        bench = job.steps.get(station=self.fin_st)
        record = check(bench.pk, self.branch, self.coordinator)
        self.assertEqual(record.outcome, 'PASSED')
        bench.refresh_from_db()
        self.assertEqual(bench.state, JobStep.State.DONE)