"""
Saving a job prices area services by their area (13 Nov 2026): the sticker job.
"""
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.jobs.pricing_engine import square_feet
from apps.jobs.services.line_pricing import area_specs, is_area, price_area_line

STICKER = NS(name='Sticker (SAV)', unit='PER_SQFT')


class LinePricingTests(SimpleTestCase):
    def test_which_services_are_priced_by_area(self):
        self.assertTrue(is_area(STICKER))
        self.assertTrue(is_area(NS(unit='PER_SQCM')))
        self.assertFalse(is_area(NS(unit='PER_COPY')))
        self.assertFalse(is_area(NS(unit=None)))

    def test_the_sticker_job_is_sixteen_and_two_thirds_square_feet(self):
        area = square_feet(4, 2) * 300
        self.assertEqual((area * Decimal('2.80')).quantize(Decimal('0.01')), Decimal('46.67'))

    def test_the_size_is_found_inside_or_beside_the_specifications(self):
        self.assertEqual(area_specs({'specifications': {'width_in': '4', 'height_in': '2'}}),
                         {'width_in': '4', 'height_in': '2'})
        self.assertEqual(area_specs({'width_in': 4, 'height_in': 2}), {'width_in': 4, 'height_in': 2})

    @patch('apps.jobs.services.line_pricing.quote_line')
    def test_the_save_paths_get_the_quote_and_the_price_of_one_piece(self, quote):
        quote.return_value = {'success': True, 'total': Decimal('46.67'), 'unit_price': Decimal('0.16'),
                              'area_sqft': Decimal('0.0556'), 'minimum_applied': False}
        out = price_area_line(STICKER, None, {'specifications': {'width_in': '4', 'height_in': '2'}}, 300)
        quote.assert_called_once_with(STICKER, None, {'width_in': '4', 'height_in': '2'}, 300)
        self.assertEqual((out['total'], out['base_price']), (Decimal('46.67'), Decimal('0.16')))

    @patch('apps.jobs.services.line_pricing.quote_line')
    def test_no_size_is_refused_not_guessed(self, quote):
        quote.return_value = {'success': False, 'error': 'Sticker (SAV) is priced by area and needs a width and a height in inches.',
                              'total': Decimal('0.00')}
        out = price_area_line(STICKER, None, {'specifications': {}}, 300)
        self.assertFalse(out['success'])
        self.assertIn('width and a height', out['error'])
