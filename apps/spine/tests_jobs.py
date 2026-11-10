"""
Job moves are named for what they mean (Layer 1, Step 1.1d).
The mapping is tested without building a real Job: record() is replaced by a
stand-in that captures what would have been written.
Run: docker compose run --rm web python manage.py test apps.spine.tests_jobs -v 2
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.spine import kinds
from apps.spine.jobs import kind_for_move, record_halt, record_job_move
from apps.spine.models import Event


def _job():
    return SimpleNamespace(pk=7, job_number='WLB-2026-00099', customer=None, branch=None)


class KindForMoveTests(SimpleTestCase):
    def test_milestones_get_their_own_names(self):
        self.assertEqual(kind_for_move('WORK', 'DONE'), kinds.JOB_READY)
        self.assertEqual(kind_for_move('HANDOVER', 'HANDED_OVER'), kinds.JOB_COLLECTED)
        self.assertEqual(kind_for_move('PAYMENT', 'SETTLED'), kinds.JOB_PAID)
        self.assertEqual(kind_for_move('PAYMENT', 'DEPOSIT_PAID'), kinds.JOB_DEPOSIT_PAID)
        self.assertEqual(kind_for_move('RECORD', 'CANCELLED'), kinds.JOB_CANCELLED)

    def test_other_moves_are_status_changes(self):
        self.assertEqual(kind_for_move('WORK', 'FINISHING'), kinds.JOB_STATUS_CHANGED)
        self.assertEqual(kind_for_move('RECORD', 'PENDING_PAYMENT'), kinds.JOB_STATUS_CHANGED)

    def test_axis_case_does_not_matter(self):
        self.assertEqual(kind_for_move('work', 'DONE'), kinds.JOB_READY)


class RecordJobMoveTests(SimpleTestCase):
    @patch('apps.spine.jobs.record')
    def test_a_move_is_keyed_by_its_status_log_row(self, record):
        log = SimpleNamespace(pk=512)
        staff = SimpleNamespace(pk=3)
        record_job_move(_job(), 'WORK', 'QUALITY_CHECK', 'DONE', staff, 'checked', log)
        kind = record.call_args.args[0]
        kwargs = record.call_args.kwargs
        self.assertEqual(kind, kinds.JOB_READY)
        self.assertEqual(kwargs['key'], 'jobstatus:512')
        self.assertEqual(kwargs['actor'], Event.STAFF)
        self.assertEqual(kwargs['payload']['from'], 'QUALITY_CHECK')
        self.assertEqual(kwargs['reason'], 'checked')

    @patch('apps.spine.jobs.record')
    def test_a_move_with_no_person_is_the_system(self, record):
        record_job_move(_job(), 'PAYMENT', 'UNPAID', 'SETTLED', None, '', SimpleNamespace(pk=1))
        self.assertEqual(record.call_args.kwargs['actor'], Event.SYSTEM)

    @patch('apps.spine.jobs.record')
    def test_a_halt_carries_its_reason(self, record):
        halt = SimpleNamespace(pk=9, reason='MACHINE_BREAKDOWN', note='head clogged',
                               work_state_at_halt='IN_PRODUCTION')
        record_halt(_job(), halt, SimpleNamespace(pk=3))
        self.assertEqual(record.call_args.args[0], kinds.JOB_HALTED)
        self.assertEqual(record.call_args.kwargs['reason'], 'MACHINE_BREAKDOWN: head clogged')
        self.assertEqual(record.call_args.kwargs['key'], 'jobhalt:9')
