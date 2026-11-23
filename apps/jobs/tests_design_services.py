"""
Graphic design in the catalogue (23 Nov 2026): GHS 150 designed and printed
with us, GHS 300 for the design and the complete file.

Run: docker compose run --rm web python manage.py test apps.jobs.tests_design_services -t .
"""
from decimal import Decimal
from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase

from apps.communications.assistant import prompt, tools
from apps.jobs.models import PricingRule, Service
from apps.jobs.services.availability import can_make

migration = import_module('apps.jobs.migrations.0058_design_services')


class DesignServiceTests(TestCase):

    def setUp(self):
        migration.add(django_apps, None)      # the test database may have run it before these rows

    def test_two_versions_of_one_product_with_their_prices(self):
        printed = Service.objects.get(code='DESIGN-PRINT')
        whole = Service.objects.get(code='DESIGN-FILE')
        self.assertEqual(whole.variant_of, printed)
        self.assertEqual(PricingRule.objects.get(service=printed, branch=None).base_price, Decimal('150.00'))
        self.assertEqual(PricingRule.objects.get(service=whole, branch=None).base_price, Decimal('300.00'))
        self.assertTrue(can_make(printed) and can_make(whole))
        self.assertFalse(printed.online or whole.online)

    def test_running_it_again_changes_nothing(self):
        migration.add(django_apps, None)
        self.assertEqual(Service.objects.filter(code__startswith='DESIGN-').count(), 2)
        self.assertEqual(PricingRule.objects.filter(service__code__startswith='DESIGN-').count(), 2)

    def test_octos_finds_and_prices_them(self):
        found = tools.find_services('can you design a banner')
        self.assertTrue(found['found'])
        codes = {s['code'] for s in found['services']}
        self.assertTrue({'DESIGN-PRINT', 'DESIGN-FILE'} & codes, codes)
        self.assertEqual(tools.quote('DESIGN-PRINT')['total'], 'GHS 150.00')
        self.assertEqual(tools.quote('DESIGN-FILE')['total'], 'GHS 300.00')

    def test_octos_knows_which_price_is_which(self):
        self.assertIn('GHS 150 when we design it and print it here', prompt.RULES)
        self.assertIn('GHS 300 when they want the design and the complete file', prompt.RULES)
