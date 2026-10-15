"""
Correcting an order during inspection.

The coordinator may change a specification only while holding the job
for inspection, only before it is cleared, only with the customer's
agreement in words, only on fields the order already has, and never
anything that sets the price. Every change is recorded.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.jobs.models import Job, JobLineItem, JobSpecChange
from apps.jobs.services.inspection import claim
from apps.jobs.status_engine import JobStatusEngine
from apps.jobs.tests import JobsFixtureMixin


class SpecChangeTests(JobsFixtureMixin, TestCase):

    def setUp(self):
        quiet = patch('apps.core.broadcast.broadcast_invalidation')
        quiet.start()
        self.addCleanup(quiet.stop)

        self.client = APIClient()
        self.client.force_authenticate(user=self.coordinator)

        self.job = Job.objects.create(
            branch=self.branch, job_type='PRODUCTION',
            status=Job.PAID, title='Spec change test',
            intake_by=None, estimated_cost=Decimal('50.00'),
            daily_sheet=self.sheet, intake_channel='ONLINE',
            payment_state='SETTLED', work_state='RECEIVED',
            handover_state='AWAITING_COLLECTION',
            estimated_ready_at=timezone.now() + timedelta(hours=1),
        )
        self.line = JobLineItem.objects.create(
            job=self.job, service=self.service,
            quantity=1, paper_size='A4',
            specifications={'size': 'A4', 'material': 'Flexy 440gsm'},
            unit_price=Decimal('50.00'), line_total=Decimal('50.00'),
        )
        self.url = f'/api/v1/jobs/{self.job.pk}/lines/{self.line.pk}/specs/'

    def _hold(self):
        claim(self.job.pk, self.branch, self.coordinator)

    def _post(self, changes, said='Agreed on the call'):
        return self.client.post(
            self.url,
            {'changes': changes, 'customer_response': said},
            format='json',
        )

    # ── What is allowed ──────────────────────────────────────────

    def test_a_held_job_can_be_corrected_and_the_price_stands(self):
        self._hold()

        response = self._post({'size': 'A3'}, said='Customer agreed A3 on the call')

        self.assertEqual(response.status_code, 200)
        self.line.refresh_from_db()
        self.assertEqual(self.line.specifications['size'], 'A3')
        self.assertEqual(self.line.unit_price, Decimal('50.00'))
        self.assertEqual(self.line.line_total, Decimal('50.00'))

        change = JobSpecChange.objects.get(job=self.job)
        self.assertEqual(
            (change.field, change.old_value, change.new_value),
            ('size', 'A4', 'A3'),
        )
        self.assertEqual(change.customer_response, 'Customer agreed A3 on the call')
        self.assertEqual(change.changed_by, self.coordinator)

    def test_a_change_to_nothing_records_nothing(self):
        self._hold()
        response = self._post({'size': 'A4'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['changes'], [])
        self.assertFalse(JobSpecChange.objects.exists())

    # ── What is refused ──────────────────────────────────────────

    def test_nothing_changes_without_the_customers_words(self):
        self._hold()
        response = self._post({'size': 'A3'}, said='   ')
        self.assertEqual(response.status_code, 400)
        self.line.refresh_from_db()
        self.assertEqual(self.line.specifications['size'], 'A4')
        self.assertFalse(JobSpecChange.objects.exists())

    def test_a_job_you_are_not_inspecting_cannot_be_changed(self):
        response = self._post({'size': 'A3'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(JobSpecChange.objects.exists())

    def test_a_cleared_job_cannot_be_changed(self):
        self._hold()
        JobStatusEngine(self.job).verify(actor=self.coordinator)

        response = self._post({'size': 'A3'})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(JobSpecChange.objects.exists())

    def test_anything_that_sets_the_price_goes_back_through_the_counter(self):
        self._hold()
        for priced in ({'quantity': 5}, {'pages': 3}, {'line_total': '1.00'}):
            with self.subTest(priced=priced):
                self.assertEqual(self._post(priced).status_code, 400)
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity, 1)
        self.assertEqual(self.line.line_total, Decimal('50.00'))

    def test_fields_the_order_never_had_cannot_be_invented(self):
        self._hold()
        response = self._post({'colour_profile': 'CMYK'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(JobSpecChange.objects.exists())

    def test_a_refused_field_cancels_the_whole_change(self):
        """
        One request, one decision. A good field alongside a refused one
        must not slip through on its own.
        """
        self._hold()
        response = self._post({'size': 'A3', 'quantity': 5})
        self.assertEqual(response.status_code, 400)
        self.line.refresh_from_db()
        self.assertEqual(self.line.specifications['size'], 'A4')
        self.assertFalse(JobSpecChange.objects.exists())