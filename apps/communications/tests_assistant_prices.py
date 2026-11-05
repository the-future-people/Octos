"""
The assistant's prices: always the counter's price, from quote_line,
the single quote path. These tests hold Octos to the engine rather than
to fixed figures, so a change to how something is priced can never make
Octos and the counter disagree.
"""
from decimal import Decimal

from django.test import TestCase

from apps.communications.assistant import tools
from apps.jobs.models import PricingRule, Service
from apps.jobs.pricing_engine import quote_line
from apps.jobs.services.availability import price_addons

SPECS = [
    {'key': 'quantity', 'type': 'number', 'label': 'Number of Copies', 'default': 1, 'min': 1, 'required': True},
    {'key': 'pages', 'type': 'number', 'label': 'Pages per Copy', 'default': 1, 'min': 1, 'required': True},
]


def service(code, name, unit, price, **extra):
    s = Service.objects.create(code=code, name=name, category='INSTANT', unit=unit, is_active=True, **extra)
    PricingRule.objects.create(service=s, branch=None, base_price=Decimal(price), is_active=True)
    return s


class PriceToolTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.prints = service('T-A4COL', 'Test A4 Colour', 'sheet', '2.50', spec_template=SPECS)
        cls.bind = service('T-BIND', 'Test Binding', 'PER_PIECE', '10.00')
        cls.prints.addons.add(cls.bind)
        cls.banner = service('T-BAN', 'Test Banner', 'PER_SQFT', '5.00')
        cls.stray = service('T-ENV', 'Test Envelope', 'PER_PIECE', '2.00')  # not an add-on of prints

    # ── Finding ─────────────────────────────────────────────────

    def test_finds_a_service_with_what_its_price_needs(self):
        found = tools.find_services('a4 colour')
        self.assertTrue(found['found'])
        (svc,) = found['services']
        self.assertEqual(svc['code'], 'T-A4COL')
        needs = {f['key']: f for f in svc['needs']}
        self.assertTrue(needs['pages']['required'])
        self.assertEqual(needs['pages']['label'], 'Pages per Copy')

    def test_nothing_said_finds_nothing(self):
        self.assertEqual(tools.find_services('  '), {'found': False, 'services': []})

    # ── Quoting ─────────────────────────────────────────────────

    def test_the_price_is_the_counters_price(self):
        facts = tools.quote('T-A4COL', {'pages': 2}, quantity=3)
        engine = quote_line(self.prints, None, {'pages': 2}, 3)
        self.assertTrue(facts['success'])
        self.assertEqual(facts['total'], f"GHS {engine['total']:.2f}")

    def test_binding_is_added_as_the_storefront_adds_it(self):
        facts = tools.quote('T-A4COL', {'pages': 2}, quantity=3, addon_codes=['T-BIND'])
        engine = quote_line(self.prints, None, {'pages': 2}, 3)['total']
        _, addons_total, problem = price_addons(self.prints, [self.bind.pk], 3, {'pages': 2})
        self.assertIsNone(problem)
        self.assertEqual(facts['total'], f'GHS {engine + addons_total:.2f}')
        self.assertEqual(facts['addons'][0]['name'], 'Test Binding')

    def test_a_banner_without_a_size_is_a_question_not_a_price(self):
        facts = tools.quote('T-BAN', {}, quantity=1)
        self.assertFalse(facts['success'])
        self.assertIn('width', facts['error'])

    def test_an_add_on_the_service_doesnt_offer_is_refused(self):
        facts = tools.quote('T-A4COL', {'pages': 1}, quantity=1, addon_codes=['T-ENV'])
        # Not offered with this service: no price, rather than a wrong one.
        self.assertFalse(facts['success'])

    def test_an_add_on_that_doesnt_exist_is_refused_not_dropped(self):
        facts = tools.quote('T-A4COL', {'pages': 1}, quantity=1, addon_codes=['LAMINATION'])
        self.assertFalse(facts['success'])
        self.assertIn('LAMINATION', facts['error'])

    def test_an_unknown_service_is_refused(self):
        self.assertFalse(tools.quote('NOPE', {}, 1)['success'])