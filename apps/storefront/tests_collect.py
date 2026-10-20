"""Collection at the counter: a PIN made once, proved before anything is handed over."""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.storefront.models import Lead, OnlineOrder
from apps.storefront.services.collection import CollectRefused, ensure_pin, find, qr_payload


class CollectionTests(TestCase):

    def setUp(self):
        self.lead = Lead.objects.create(phone='0244999888', first_name='Ama')
        self.order = OnlineOrder.objects.create(
            lead=self.lead, total=Decimal('42.00'), full_total=Decimal('42.00'), paid_at=timezone.now(),
        )

    def test_a_pin_is_four_digits_and_made_once(self):
        pin = ensure_pin(self.order)
        self.assertRegex(pin, r'^\d{4}$')
        self.assertEqual(ensure_pin(self.order), pin)

    def test_the_qr_carries_the_order_and_its_pin(self):
        pin = ensure_pin(self.order)
        self.assertEqual(qr_payload(self.order), f'PO:{self.order.order_number}:{pin}')

    def test_a_pin_is_always_asked_for(self):
        with self.assertRaises(CollectRefused):
            find(phone='0244999888', pin='')

    def test_a_wrong_pin_learns_nothing(self):
        ensure_pin(self.order)
        with self.assertRaises(CollectRefused) as wrong:
            find(phone='0244999888', pin='0000' if self.order.collection_pin != '0000' else '1111')
        with self.assertRaises(CollectRefused) as nobody:
            find(phone='0200000000', pin='1234')
        self.assertEqual(str(wrong.exception), str(nobody.exception))

    def test_an_order_not_yet_ready_cannot_be_found(self):
        pin = ensure_pin(self.order)   # no job: not made yet
        with self.assertRaises(CollectRefused):
            find(phone='0244999888', pin=pin)

    def test_a_strange_qr_is_refused(self):
        with self.assertRaises(CollectRefused):
            find(qr='https://example.com')

    def test_the_counter_needs_staff(self):
        self.assertEqual(APIClient().get('/api/v1/storefront/collect/', {'phone': '0244999888', 'pin': '1'}).status_code, 401)

    def test_the_ready_text_carries_the_pin(self):
        from apps.storefront.services.messages import ready_text
        pin = ensure_pin(self.order)
        self.assertIn(pin, ready_text(self.order))
        self.assertLessEqual(len(ready_text(self.order)), 160)
