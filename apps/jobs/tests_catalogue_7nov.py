"""
The catalogue, 7 Nov 2026: one envelope for all copies by default, A3
packing, and packing never inspected against the job's file.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.jobs.services.availability import addon_quantity, is_packing
from apps.jobs.services.intake_check import _takes_no_file

ENVELOPE = SimpleNamespace(code='ENV-PACK-A4', unit='PER_PIECE')


def service(name, requires_file_upload=False, category='INSTANT', offered_as_addon=False):
    return SimpleNamespace(name=name, requires_file_upload=requires_file_upload, category=category,
                           addon_for=SimpleNamespace(exists=lambda: offered_as_addon))


class PackingTests(SimpleTestCase):

    def test_one_envelope_for_all_copies_by_default(self):
        self.assertEqual(addon_quantity(ENVELOPE, 3, {'pages': 3}), 1)

    def test_one_each_when_the_customer_asks(self):
        self.assertEqual(addon_quantity(ENVELOPE, 3, {'pages': 3}, per_copy=True), 3)

    def test_a3_packing_is_packing(self):
        self.assertTrue(is_packing(SimpleNamespace(code='ENV-PACK-A3')))


class NeverInspectedTests(SimpleTestCase):

    def test_an_envelope_is_not_inspected_against_the_job_file(self):
        self.assertTrue(_takes_no_file(service('A4 Brown Envelope')))

    def test_lamination_offered_as_an_addon_is_not_either(self):
        self.assertTrue(_takes_no_file(service('A4 Lamination', offered_as_addon=True)))

    def test_prints_and_passport_photos_still_are(self):
        self.assertFalse(_takes_no_file(service('A4 Color Printing 1-sided', requires_file_upload=True)))
        self.assertFalse(_takes_no_file(service('Passport Photo (American)')))
