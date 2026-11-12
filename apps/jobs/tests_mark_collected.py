"""
Marking a ready job collected from the BM's page (12 Nov 2026).
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.jobs.selectors.workload_selectors import _recorded_by
from apps.jobs.services.mark_collected import Refused, mark_collected


class RecordedByTests(SimpleTestCase):
    def test_an_attendant_is_named(self):
        job = SimpleNamespace(intake_by_id=3, intake_by=SimpleNamespace(full_name='Ama Mensah'), intake_channel='WALK_IN')
        self.assertEqual(_recorded_by(job), 'Ama Mensah')

    def test_an_online_order_says_print_octos(self):
        job = SimpleNamespace(intake_by_id=None, intake_by=None, intake_channel='ONLINE')
        self.assertEqual(_recorded_by(job), 'Print Octos (online)')

    def test_an_unknown_walk_in_is_a_dash(self):
        job = SimpleNamespace(intake_by_id=None, intake_by=None, intake_channel='WALK_IN')
        self.assertEqual(_recorded_by(job), '—')


class MarkCollectedRuleTests(SimpleTestCase):
    def _job(self, handover='AWAITING_COLLECTION'):
        return SimpleNamespace(handover_state=handover)

    def test_a_reason_is_required(self):
        with self.assertRaises(Refused):
            mark_collected(self._job(), SimpleNamespace(full_name='BM'), reason='')

    def test_other_needs_a_note(self):
        with self.assertRaises(Refused):
            mark_collected(self._job(), SimpleNamespace(full_name='BM'), reason='OTHER', note=' ')

    def test_a_collected_job_is_not_collected_twice(self):
        with self.assertRaises(Refused):
            mark_collected(self._job('HANDED_OVER'), SimpleNamespace(full_name='BM'), reason='TEST_JOB')
