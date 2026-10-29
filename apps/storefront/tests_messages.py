"""
The customer's texts: warm, short enough for one SMS, and always the
number the customer was actually given.

Plain stand-ins rather than database rows: the message functions only
read attributes, so the edge cases can be pushed hard and run instantly.
"""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace as NS

from django.test import SimpleTestCase
from django.utils import timezone

from apps.storefront.services import messages as m


def _order(name='Abena', lines=None, number='ORD-2026-00043', counter=None,
           branch='Westland Branch', total='117.00', pin='4821', hours=3):
    return NS(
        lead=NS(first_name=name),
        line_items=lines if lines is not None else [{'service_name': 'Flexy Banner', 'quantity': 1}],
        order_number=number,
        payment_reference=f'COUNTER:{counter}' if counter else 'PSK-REF-001',
        total=Decimal(total),
        short_code='K3P9QW2M',
        promised_for=(timezone.now() + timedelta(hours=hours)) if hours is not None else None,
        branch_id=1 if branch else None,
        branch=NS(name=branch) if branch else None,
        collection_pin=pin,
    )


class OneMessageTests(SimpleTestCase):

    def test_every_text_fits_one_sms_at_its_longest(self):
        long = _order(name='Bartholomew', number='ORD-2026-99999', counter='FP-KWM-2026-99999',
                      branch='Kwashieman Branch', total='12500.00', hours=50)
        texts = [
            m.payment_text(long),
            m.counter_paid_text(long, Decimal('9999.99')),
            m.ready_text(long),
            m.late_text(long, '12:45pm tomorrow'),
            m.changed_text(long, '12:45pm tomorrow'),
            m.code_text('123456'),
        ]
        for text in texts:
            with self.subTest(text=text):
                self.assertLessEqual(len(text), m.LIMIT)


class NameTests(SimpleTestCase):

    def test_a_real_first_name_is_greeted_in_proper_case(self):
        self.assertIn('Hi Abena,', m.payment_text(_order(name='aBENA')))
        self.assertTrue(m.ready_text(_order()).startswith('Good news, Abena!'))

    def test_junk_and_placeholders_drop_the_greeting(self):
        for junk in ['On whatsup', 'Customer', 'A', 'x1', '', 'Walkin']:
            with self.subTest(name=junk):
                self.assertNotIn('Hi ', m.payment_text(_order(name=junk)))
                self.assertTrue(m.ready_text(_order(name=junk)).startswith('Good news!'))
                self.assertTrue(m.late_text(_order(name=junk), '5:15pm today').startswith('Sorry,'))


class ReferenceTests(SimpleTestCase):

    def test_a_counter_job_gets_its_job_number_short(self):
        text = m.counter_paid_text(_order(number='ORD-2026-00051', counter='FP-WLB-2026-05629'))
        self.assertIn('ref 5629', text)
        self.assertNotIn('ORD', text)
        self.assertNotIn('FP-WLB', text)

    def test_an_online_order_gets_its_order_number_short(self):
        text = m.payment_text(_order(number='ORD-2026-00043'))
        self.assertIn('ref 43', text)
        self.assertNotIn('ORD-2026', text)


class WhatTheyOrderedTests(SimpleTestCase):

    def test_one_item_is_named(self):
        self.assertIn('your flexy banner', m.late_text(_order(), '5:15pm today'))

    def test_several_items_or_several_of_one_or_a_code_like_name_is_your_order(self):
        cases = [
            [{'service_name': 'Flexy Banner', 'quantity': 1}, {'service_name': 'Stickers', 'quantity': 1}],
            [{'service_name': 'Flexy Banner', 'quantity': 2}],
            [{'service_name': 'A4 Color Printing 1-sided', 'quantity': 1}],
        ]
        for lines in cases:
            with self.subTest(lines=lines):
                self.assertIn('your order', m.late_text(_order(lines=lines), '5:15pm today'))


class WhatEachTextSaysTests(SimpleTestCase):

    def test_ready_carries_the_pin_and_the_link(self):
        text = m.ready_text(_order(pin='4821'))
        self.assertIn('PIN 4821', text)
        self.assertIn('/t/K3P9QW2M', text)

    def test_late_owns_the_delay(self):
        self.assertIn('taking longer than we promised', m.late_text(_order(), '5:15pm today'))

    def test_the_counter_text_names_a_balance_only_when_one_is_owed(self):
        self.assertIn('balance GHS 30.00', m.counter_paid_text(_order(counter='FP-WLB-2026-05629'), Decimal('30')))
        self.assertNotIn('balance', m.counter_paid_text(_order(counter='FP-WLB-2026-05629'), Decimal('0')))