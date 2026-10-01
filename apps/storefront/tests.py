from django.test import TestCase

# Create your tests here.
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.storefront.models import Lead, OnlineOrder


class LeadTests(TestCase):
    """
    A first visit creates a lead, not a customer. Most first visits never
    come back, and writing every one into CustomerProfile would fill the
    customer table with people the shop has met once.
    """

    def test_a_new_lead_is_not_returning_and_has_no_pin(self):
        lead = Lead.objects.create(phone='0244000001', first_name='Ama')
        self.assertFalse(lead.is_returning)
        self.assertFalse(lead.has_pin)

    def test_a_pin_is_hashed_never_stored_as_typed(self):
        """
        Four digits is weak by nature. Storing it in the clear would make
        one database leak a list of working PINs.
        """
        lead = Lead.objects.create(phone='0244000002', first_name='Kofi')
        lead.set_pin('1234')
        lead.save()
        lead.refresh_from_db()

        self.assertNotEqual(lead.pin, '1234')
        self.assertNotIn('1234', lead.pin)
        self.assertTrue(lead.check_pin('1234'))
        self.assertFalse(lead.check_pin('4321'))

    def test_a_phone_number_belongs_to_one_lead(self):
        from django.db import IntegrityError
        Lead.objects.create(phone='0244000003', first_name='Yaa')
        with self.assertRaises(IntegrityError):
            Lead.objects.create(phone='0244000003', first_name='Someone else')


class OnlineOrderTests(TestCase):
    """
    An order exists from the moment someone starts building it, before
    any branch knows about it and before anyone has paid. Most are
    abandoned, which costs nothing.
    """

    def _order(self, **overrides):
        defaults = dict(total=Decimal('568.75'))
        defaults.update(overrides)
        return OnlineOrder.objects.create(**defaults)

    def test_an_order_numbers_itself(self):
        order = self._order()
        year = timezone.localdate().year
        self.assertTrue(order.order_number.startswith(f'ORD-{year}-'))

    def test_every_order_gets_its_own_number(self):
        """
        From a sequence, not from the highest so far. Two strangers can
        click in the same millisecond.
        """
        numbers = {self._order().order_number for _ in range(5)}
        self.assertEqual(len(numbers), 5)

    def test_an_order_starts_as_a_draft_owned_by_nobody(self):
        order = self._order()
        self.assertEqual(order.status, OnlineOrder.Status.DRAFT)
        self.assertIsNone(order.branch_id)
        self.assertIsNone(order.lead_id)
        self.assertIsNone(order.job_id)
        self.assertFalse(order.is_paid)
        self.assertTrue(order.is_open)

    def test_an_order_is_not_paid_until_the_webhook_says_so(self):
        """
        paid_at is set by the provider's callback, never by the customer
        returning to the page. Someone who closes the tab after paying
        has still paid.
        """
        order = self._order(
            status=OnlineOrder.Status.AWAITING_PAYMENT,
            payment_reference='ORD-TEST-REF-001',
        )
        self.assertFalse(order.is_paid)

        order.paid_at = timezone.now()
        order.status = OnlineOrder.Status.PAID
        order.save()

        self.assertTrue(order.is_paid)
        self.assertFalse(order.is_open)

    def test_line_items_carry_the_specification(self):
        """
        A banner's size has to survive into the job, or the floor gets a
        banner with no dimensions on it.
        """
        order = self._order(line_items=[{
            'service_name': 'Flexy Banner',
            'quantity': 1,
            'unit_price': '568.75',
            'total': '568.75',
            'specifications': {'width_in': 168, 'height_in': 150},
        }])
        order.refresh_from_db()
        self.assertEqual(
            order.line_items[0]['specifications']['width_in'], 168,
        )