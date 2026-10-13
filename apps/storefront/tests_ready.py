"""
The text a customer is actually waiting for: their order is ready.

Sent when the floor marks the job done, from the worker rather than the
coordinator's tap, to the phone on the online order. Walk-ins get nothing
yet; they have not been asked whether they want texts.
"""

import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.finance.models import DailySalesSheet
from apps.organization.models import Branch
from apps.storefront.models import Lead, OnlineOrder


class ReadyTextTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(
            name='Ready Branch', code='RDB',
            is_headquarters=False, is_regional_hq=False,
            address='5 Ready Road, Accra', phone='0302000333',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30), closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )

    def _converted(self):
        """A paid order that has become a job, as the floor would see it."""
        from apps.storefront.services.conversion import convert

        DailySalesSheet.objects.get_or_create(
            branch=self.branch, date=timezone.localdate(),
            defaults={'status': DailySalesSheet.Status.OPEN},
        )
        lead = Lead.objects.create(phone='0244700911', first_name='Kwesi')
        order = OnlineOrder.objects.create(
            lead=lead, branch=self.branch,
            total=Decimal('50.00'), full_total=Decimal('50.00'),
            status=OnlineOrder.Status.PAID, paid_at=timezone.now(),
        )
        with patch('apps.storefront.services.conversion.send_sms'):
            job = convert(order)
        order.refresh_from_db()
        return order, job

    def test_it_texts_the_phone_on_the_order(self):
        from apps.storefront.tasks import tell_customer_ready

        order, job = self._converted()
        with patch('apps.storefront.services.sms.send_sms') as sent:
            tell_customer_ready.apply(args=(job.pk,))

        self.assertTrue(sent.called)
        phone, message = sent.call_args[0][:2]
        self.assertEqual(phone, '0244700911')
        self.assertIn('ready', message.lower())
        self.assertIn(order.order_number, message)

    def test_a_job_with_no_online_order_texts_nobody(self):
        from apps.storefront.tasks import tell_customer_ready

        with patch('apps.storefront.services.sms.send_sms') as sent:
            tell_customer_ready.apply(args=(0,))

        self.assertFalse(sent.called)

    def test_it_fits_in_one_message(self):
        from apps.storefront.services.messages import ready_text

        order, _ = self._converted()
        self.assertLessEqual(len(ready_text(order)), 160)