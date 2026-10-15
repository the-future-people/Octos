"""
Paid money must reach the floor once, and only once.

Conversion has more than one road now: the worker, the hourly sweep, and
the customer's own confirmation page. Any of them may run at the same
moment as another. These prove a second caller finds the first one's job
rather than making a second, and that the confirmation page fills the
gap when the worker has not.
"""

import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.finance.models import DailySalesSheet
from apps.jobs.models import Job
from apps.organization.models import Branch
from apps.storefront.models import Lead, OnlineOrder
from apps.storefront.services.conversion import convert


class ConversionSafetyTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(
            name='Safety Branch', code='CSB',
            is_headquarters=False, is_regional_hq=False,
            address='6 Safety Road, Accra', phone='0302000444',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30), closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )

    def setUp(self):
        DailySalesSheet.objects.get_or_create(
            branch=self.branch, date=timezone.localdate(),
            defaults={'status': DailySalesSheet.Status.OPEN},
        )
        quiet = patch('apps.storefront.services.conversion.send_sms')
        quiet.start()
        self.addCleanup(quiet.stop)

    def _paid_order(self):
        lead = Lead.objects.create(phone='0244700922', first_name='Yaa')
        return OnlineOrder.objects.create(
            lead=lead, branch=self.branch,
            total=Decimal('75.00'), full_total=Decimal('75.00'),
            status=OnlineOrder.Status.PAID, paid_at=timezone.now(),
        )

    def test_a_second_caller_gets_the_same_job(self):
        """
        Two callers holding their own copy of the order, as the worker and
        a confirmation page would. The second must find the first's job.
        """
        order = self._paid_order()
        stale = OnlineOrder.objects.get(pk=order.pk)
        before = Job.objects.count()

        first = convert(order)
        second = convert(stale)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Job.objects.count(), before + 1)

    def test_the_confirmation_page_converts_a_paid_order_with_no_job(self):
        order = self._paid_order()

        response = APIClient().get(
            f'/api/v1/storefront/confirm/{order.order_number}/'
        )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertIsNotNone(order.job_id)

    def test_the_confirmation_page_leaves_a_converted_order_alone(self):
        order = self._paid_order()
        convert(order)
        before = Job.objects.count()

        APIClient().get(f'/api/v1/storefront/confirm/{order.order_number}/')

        self.assertEqual(Job.objects.count(), before)