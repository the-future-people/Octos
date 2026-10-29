"""
The operator's machine: Start, slack order, and every line ending at the bench.

A small floor: one DTF printer with an operator assigned, and the hand-
finishing bench. Transfers are printed and nothing more, so their route
ends on the machine and the bench step is added for them.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.jobs.models import Job, JobLineItem, JobStep, Service
from apps.jobs.services.steps import (
    StepRefused, build_steps, mark_done, queue, report_problem, start_step,
)
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

    def test_a_sent_back_piece_returns_clean_and_waits_for_start(self):
        from apps.jobs.services.final_check import _send_back
        job = self._job(quantity=2)
        build_steps(job)
        start_step(self._print(job).pk, self.branch, self.operator)
        mark_done(self._print(job).pk, self.branch, self.operator, made=2, spoilt=1)

        _send_back(job.steps.get(station=self.fin_st), self.branch)

        step = self._print(job)
        self.assertEqual(step.state, JobStep.State.WAITING)
        self.assertIsNone(step.started_at)
        self.assertIsNone(step.started_by)
        self.assertIsNone(step.quantity_made)
        self.assertIsNone(step.quantity_spoilt)
        # Back at the front of a staffed machine: recorded, waiting for Start.
        self.assertIsNotNone(step.reached_at)

        start_step(step.pk, self.branch, self.operator)
        self.assertEqual(self._print(job).state, JobStep.State.ACTIVE)

    # ── The API ──────────────────────────────────────────────────

    def _client(self, user):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_api_queue_shows_my_machine_and_no_money(self):
        job = self._job()
        build_steps(job)
        resp = self._client(self.operator).get('/api/v1/jobs/operator/queue/')
        self.assertEqual(resp.status_code, 200, resp.data)

        machine = resp.data['machines'][0]
        self.assertEqual(machine['name'], 'DTF printer')
        self.assertIsNone(machine['running'])
        self.assertEqual(machine['next']['step'], self._print(job).pk)
        self.assertIsInstance(machine['next']['slack_minutes'], int)
        body = str(resp.data)
        for word in ('estimated_cost', 'price', 'phone'):
            self.assertNotIn(word, body)

    def test_api_queue_refuses_someone_not_on_a_machine(self):
        resp = self._client(self.coordinator).get('/api/v1/jobs/operator/queue/')
        self.assertEqual(resp.status_code, 403, resp.data)

    @patch('apps.core.broadcast.broadcast_invalidation')
    def test_api_start_then_done(self, _broadcast):
        job = self._job(quantity=2)
        build_steps(job)
        client = self._client(self.operator)
        pk = self._print(job).pk

        resp = client.post(f'/api/v1/jobs/operator/steps/{pk}/start/')
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = client.post(f'/api/v1/jobs/operator/steps/{pk}/done/',
                           {'made': 2, 'spoilt': 0}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

        step = self._print(job)
        self.assertEqual(step.state, JobStep.State.DONE)
        self.assertEqual((step.quantity_made, step.quantity_spoilt), (2, 0))

    @patch('apps.core.broadcast.broadcast_invalidation')
    def test_api_done_needs_both_counts(self, _broadcast):
        job = self._job()
        build_steps(job)
        client = self._client(self.operator)
        pk = self._print(job).pk
        client.post(f'/api/v1/jobs/operator/steps/{pk}/start/')

        resp = client.post(f'/api/v1/jobs/operator/steps/{pk}/done/',
                           {'made': '', 'spoilt': 0}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(self._print(job).state, JobStep.State.ACTIVE)

    @patch('apps.core.broadcast.broadcast_invalidation')
    def test_api_done_refuses_someone_not_on_the_machine(self, _broadcast):
        job = self._job()
        build_steps(job)
        pk = self._print(job).pk
        self._client(self.operator).post(f'/api/v1/jobs/operator/steps/{pk}/start/')

        resp = self._client(self.coordinator).post(
            f'/api/v1/jobs/operator/steps/{pk}/done/', {'made': 1, 'spoilt': 0}, format='json',
        )
        self.assertEqual(resp.status_code, 403, resp.data)

    def test_api_unlock_checks_the_operators_own_password(self):
        client = self._client(self.operator)
        wrong = client.post('/api/v1/jobs/operator/unlock/', {'password': 'nope'}, format='json')
        self.assertEqual(wrong.status_code, 403)
        right = client.post('/api/v1/jobs/operator/unlock/', {'password': 'test-pass-123'}, format='json')
        self.assertEqual(right.status_code, 200, right.data)

    # ── Problem ──────────────────────────────────────────────────

    def _two_running(self):
        """Two jobs on the DTF; the first started."""
        first = self._job(promise_in_hours=1)
        second = self._job(promise_in_hours=5)
        build_steps(first)
        build_steps(second)
        start_step(self._print(first).pk, self.branch, self.operator)
        return first, second

    def _open_halt(self, job):
        return job.halts.filter(resumed_at__isnull=True).first()

    def test_file_fault_sets_the_job_aside_and_the_machine_carries_on(self):
        first, second = self._two_running()
        report_problem(self._print(first).pk, self.branch, self.operator, 'FILE_FAULT', 'Low resolution')

        off = self._print(first)
        self.assertEqual(off.state, JobStep.State.WAITING)
        self.assertIsNone(off.started_at)
        self.assertEqual(self._open_halt(first).reason, 'FILE_FAULT')

        self.dtf.refresh_from_db()
        self.assertTrue(self.dtf.is_available)
        line_up = list(queue(self.branch, machine=self.dtf))
        self.assertEqual([s.job_id for s in line_up], [second.pk])
        self.assertIsNotNone(line_up[0].reached_at)

    def test_material_out_stops_only_this_job(self):
        first, second = self._two_running()
        report_problem(self._print(first).pk, self.branch, self.operator, 'MATERIAL_OUT')

        self.assertEqual(self._open_halt(first).reason, 'MATERIALS_OUT')
        self.assertIsNone(self._open_halt(second))
        self.assertEqual([s.job_id for s in queue(self.branch, machine=self.dtf)], [second.pk])

    def test_machine_down_takes_the_machine_out(self):
        first, _ = self._two_running()
        report_problem(self._print(first).pk, self.branch, self.operator, 'MACHINE_DOWN', 'Head clogged')

        self.dtf.refresh_from_db()
        self.assertFalse(self.dtf.is_available)
        self.assertEqual(self._open_halt(first).reason, 'MACHINE_BREAKDOWN')

    def test_a_problem_must_be_one_of_the_three(self):
        first, _ = self._two_running()
        with self.assertRaises(StepRefused):
            report_problem(self._print(first).pk, self.branch, self.operator, 'BORED')

    def test_a_problem_is_only_on_my_own_machine(self):
        first, _ = self._two_running()
        with self.assertRaises(StepRefused) as ctx:
            report_problem(self._print(first).pk, self.branch, self.coordinator, 'FILE_FAULT')
        self.assertIn('not on your machine', str(ctx.exception))
        self.assertIsNone(self._open_halt(first))

    @patch('apps.core.broadcast.broadcast_invalidation')
    def test_api_problem(self, _broadcast):
        first, _ = self._two_running()
        resp = self._client(self.operator).post(
            f'/api/v1/jobs/operator/steps/{self._print(first).pk}/problem/',
            {'kind': 'file_fault', 'note': 'Wrong size'}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self._open_halt(first).reason, 'FILE_FAULT')

    def test_api_files_reach_the_card_print_file_first(self):
        from apps.jobs.models import JobFile
        job = self._job()
        other = self._job(promise_in_hours=9)
        build_steps(job)
        build_steps(other)
        line = job.line_items.get()

        JobFile.objects.create(job=job, line_item=line, file='jobs/t/crest_original.pdf', file_type='ORIGINAL')
        JobFile.objects.create(job=job, line_item=line, file='jobs/t/crest_final.pdf', file_type='FINAL')
        JobFile.objects.create(job=job, line_item=None, file='jobs/t/brand_guide.pdf', file_type='REFERENCE')
        JobFile.objects.create(job=other, line_item=other.line_items.get(),
                               file='jobs/t/someone_else.pdf', file_type='FINAL')

        resp = self._client(self.operator).get('/api/v1/jobs/operator/queue/')
        self.assertEqual(resp.status_code, 200, resp.data)
        files = resp.data['machines'][0]['next']['files']

        self.assertEqual([f['name'] for f in files],
                         ['crest_final.pdf', 'crest_original.pdf', 'brand_guide.pdf'])
        for f in files:
            self.assertTrue(f['url'].startswith(f"/api/v1/jobs/files/{f['id']}/?t="))
        self.assertNotIn('someone_else.pdf', str(resp.data['machines'][0]['next']))

    # ── Done on a staffed machine is the operator's ──────────────

    def _started(self):
        job = self._job()
        build_steps(job)
        start_step(self._print(job).pk, self.branch, self.operator)
        return job

    def test_someone_else_cannot_close_a_staffed_machines_job_without_a_reason(self):
        job = self._started()
        with self.assertRaises(StepRefused) as ctx:
            mark_done(self._print(job).pk, self.branch, self.coordinator)
        self.assertIn('Done is theirs', str(ctx.exception))
        self.assertEqual(self._print(job).state, JobStep.State.ACTIVE)

    def test_a_coordinator_can_override_with_a_reason_and_it_is_kept(self):
        job = self._started()
        mark_done(self._print(job).pk, self.branch, self.coordinator,
                  override='Operator went home; banner is printed')
        step = self._print(job)
        self.assertEqual(step.state, JobStep.State.DONE)
        self.assertEqual(step.done_by, self.coordinator)
        self.assertEqual(step.done_override, 'Operator went home; banner is printed')

    def test_the_operators_own_done_keeps_no_override(self):
        job = self._started()
        mark_done(self._print(job).pk, self.branch, self.operator, override='stray text')
        self.assertEqual(self._print(job).done_override, '')

    def test_a_reprint_clears_the_override(self):
        from apps.jobs.services.final_check import _send_back
        job = self._started()
        mark_done(self._print(job).pk, self.branch, self.coordinator, override='Operator left')
        _send_back(job.steps.get(station=self.fin_st), self.branch)
        self.assertEqual(self._print(job).done_override, '')

    @patch('apps.core.broadcast.broadcast_invalidation')
    def test_api_coordinator_done_needs_a_reason_on_a_staffed_machine(self, _broadcast):
        job = self._started()
        client = self._client(self.coordinator)
        url = f'/api/v1/jobs/steps/{self._print(job).pk}/done/'

        refused = client.post(url, {}, format='json')
        self.assertEqual(refused.status_code, 400, refused.data)
        self.assertIn('Done is theirs', refused.data['detail'])

        allowed = client.post(url, {'override': 'Operator went home'}, format='json')
        self.assertEqual(allowed.status_code, 200, allowed.data)
        self.assertEqual(self._print(job).done_override, 'Operator went home')