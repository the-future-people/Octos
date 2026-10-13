"""
The arrivals queue and who is inspecting what.

Strict by design: the coordinator takes the job at the top, never one
further down. Order comes from the promise Octos made, a claim stops two
people checking the same file, and an abandoned claim lapses so a tablet
left on a bench cannot hold the queue.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.jobs.models import Job
from apps.jobs.services.inspection import (
    CLAIM_TTL, ClaimRefused, arrival_queue, claim, next_up, release,
)
from apps.jobs.tests import JobsFixtureMixin


class InspectionQueueTests(JobsFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.kojo = User(
            employee_id='TST-FC-002',
            first_name='Kojo', last_name='Mensah',
            email='kojo@test.local',
            employment_status='ACTIVE',
            is_active=True, is_staff=False, is_superuser=False,
            is_clocked_in=False, must_change_password=False,
            is_business_owner=False, download_pin_set=False,
            branch=cls.branch, role=cls.coordinator_role,
        )
        cls.kojo.set_password('test-pass-123')
        cls.kojo.save()

    def _job(self, promise_in_hours=None, **overrides):
        promise = (
            timezone.now() + timedelta(hours=promise_in_hours)
            if promise_in_hours is not None else None
        )
        defaults = dict(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PAID, title='Inspection test',
            intake_by=None, estimated_cost=Decimal('100.00'),
            daily_sheet=self.sheet, intake_channel='ONLINE',
            payment_state='SETTLED', work_state='RECEIVED',
            handover_state='AWAITING_COLLECTION',
            estimated_ready_at=promise,
        )
        defaults.update(overrides)
        return Job.objects.create(**defaults)

    # ── Order ────────────────────────────────────────────────────

    def test_soonest_promise_comes_first(self):
        later = self._job(promise_in_hours=5)
        sooner = self._job(promise_in_hours=1)
        self.assertEqual(
            [j.pk for j in arrival_queue(self.branch)], [sooner.pk, later.pk],
        )

    def test_ties_go_to_whoever_arrived_first(self):
        promise = timezone.now() + timedelta(hours=2)
        first = self._job(estimated_ready_at=promise)
        second = self._job(estimated_ready_at=promise)
        self.assertEqual(
            [j.pk for j in arrival_queue(self.branch)], [first.pk, second.pk],
        )

    def test_unpromised_work_waits_behind_promised_work(self):
        unpromised = self._job()
        promised = self._job(promise_in_hours=3)
        self.assertEqual(
            [j.pk for j in arrival_queue(self.branch)],
            [promised.pk, unpromised.pk],
        )

    # ── Claiming ─────────────────────────────────────────────────

    def test_only_the_next_job_can_be_taken(self):
        first = self._job(promise_in_hours=1)
        second = self._job(promise_in_hours=2)

        with self.assertRaises(ClaimRefused):
            claim(second.pk, self.branch, self.coordinator)

        claim(first.pk, self.branch, self.coordinator)
        first.refresh_from_db()
        self.assertEqual(first.inspecting_by, self.coordinator)

    def test_nobody_can_take_a_job_someone_else_holds(self):
        first = self._job(promise_in_hours=1)
        claim(first.pk, self.branch, self.coordinator)

        with self.assertRaises(ClaimRefused):
            claim(first.pk, self.branch, self.kojo)

    def test_the_second_coordinator_gets_the_next_job(self):
        first = self._job(promise_in_hours=1)
        second = self._job(promise_in_hours=2)
        claim(first.pk, self.branch, self.coordinator)

        mine = next_up(arrival_queue(self.branch), self.kojo)
        self.assertEqual(mine.pk, second.pk)
        claim(second.pk, self.branch, self.kojo)

    def test_your_own_job_stays_yours_while_you_hold_it(self):
        first = self._job(promise_in_hours=1)
        self._job(promise_in_hours=2)
        claim(first.pk, self.branch, self.coordinator)

        mine = next_up(arrival_queue(self.branch), self.coordinator)
        self.assertEqual(mine.pk, first.pk)

    def test_an_abandoned_claim_lapses(self):
        first = self._job(promise_in_hours=1)
        claim(first.pk, self.branch, self.coordinator)
        Job.objects.filter(pk=first.pk).update(
            inspecting_since=timezone.now() - CLAIM_TTL - timedelta(minutes=1),
        )

        claim(first.pk, self.branch, self.kojo)
        first.refresh_from_db()
        self.assertEqual(first.inspecting_by, self.kojo)

    def test_claiming_again_keeps_the_claim_alive(self):
        first = self._job(promise_in_hours=1)
        claim(first.pk, self.branch, self.coordinator)
        stale = timezone.now() - timedelta(minutes=9)
        Job.objects.filter(pk=first.pk).update(inspecting_since=stale)

        claim(first.pk, self.branch, self.coordinator)
        first.refresh_from_db()
        self.assertGreater(first.inspecting_since, stale)

    # ── Releasing ────────────────────────────────────────────────

    def test_release_frees_only_your_own_claim(self):
        first = self._job(promise_in_hours=1)
        claim(first.pk, self.branch, self.coordinator)

        release(first, self.kojo)
        first.refresh_from_db()
        self.assertEqual(first.inspecting_by, self.coordinator)

        release(first, self.coordinator)
        first.refresh_from_db()
        self.assertIsNone(first.inspecting_by)