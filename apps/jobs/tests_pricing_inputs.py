"""
Pages and sheets (7 Nov 2026): every channel passes the document's pages,
and the engine charges both-sides products by the sheet. Typing's tiers,
binding by ring and sets, and the flyer minimum.
"""
from decimal import Decimal

from django.test import TestCase

from apps.jobs.models import PricingRule, Service
from apps.jobs.pricing_engine import quote_line


class PagesAndSheetsTests(TestCase):

    def make(self, code, unit='sheet', price='1.00', sides='SINGLE', form=None, tiers=None):
        s = Service.objects.create(code=code, name=code, category='INSTANT', unit=unit, is_active=True,
                                   smart_defaults={'sides': sides}, spec_template=form or [])
        PricingRule.objects.create(service=s, branch=None, base_price=Decimal(price), is_active=True,
                                   pricing_tiers=tiers)
        return s

    def total(self, service, quantity=1, **specs):
        line = quote_line(service, None, specs, quantity)
        self.assertTrue(line['success'], line.get('error'))
        return line['total']

    def test_both_sides_is_charged_by_the_sheet(self):
        both = self.make('BOTH', price='1.50', sides='DOUBLE')
        self.assertEqual(self.total(both, quantity=3, pages=9), Decimal('22.50'))   # 5 sheets x 1.50 x 3
        self.assertEqual(self.total(both, quantity=1, pages=10), Decimal('7.50'))   # 5 sheets

    def test_lamination_on_both_sides_counts_sheets(self):
        from apps.jobs.services.availability import price_addons
        both = self.make('BOTH2', price='1.50', sides='DOUBLE')
        lam = self.make('LAM', price='10.00')
        both.addons.add(lam)
        priced, total, problem = price_addons(both, [lam.pk], quantity=2, specs={'pages': 9})
        self.assertIsNone(problem)
        self.assertEqual(priced[0]['quantity'], 10)   # 5 sheets x 2 copies

    def test_one_side_is_every_page(self):
        one = self.make('ONE', price='1.00')
        self.assertEqual(self.total(one, quantity=3, pages=9), Decimal('27.00'))

    def test_typing_every_page_at_ten_from_ten_pages(self):
        typing = self.make('TYPE', price='20.00', tiers=[
            {'min': 1, 'max': 9, 'price_per_unit': 20.0}, {'min': 10, 'max': None, 'price_per_unit': 10.0}])
        self.assertEqual(self.total(typing, pages=9), Decimal('180.00'))
        self.assertEqual(self.total(typing, pages=10), Decimal('100.00'))
        self.assertEqual(self.total(typing, pages=25), Decimal('250.00'))

    def test_binding_is_the_ring_price_per_set(self):
        binding = self.make('BIND', unit='piece', price='10.00', tiers=[
            {'min': 8, 'max': 20, 'condition': 'ring_size', 'flat_price': 10.0},
            {'min': 22, 'max': 30, 'condition': 'ring_size', 'flat_price': 15.0}])
        self.assertEqual(self.total(binding, quantity=3, ring_size=22), Decimal('45.00'))

    def test_flyers_have_a_minimum_of_ten(self):
        flyer = self.make('FLY', unit='PER_COPY', price='3.00',
                          form=[{'key': 'quantity', 'min': 10, 'type': 'number'}])
        refused = quote_line(flyer, None, {}, 9)
        self.assertFalse(refused['success'])
        self.assertIn('minimum of 10', refused['error'])
        self.assertEqual(self.total(flyer, quantity=10), Decimal('30.00'))
