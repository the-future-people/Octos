"""
One number, one lead: however a customer types it, they find the lead they
already have. On 28 Oct 2026 a returning customer typed 0556244194, missed
their lead stored as +233556244194, and got a second one.
"""

from django.test import TestCase

from apps.storefront.models import Lead
from apps.storefront.services.accounts import find_lead


class FindLeadTests(TestCase):

    def test_the_local_form_finds_the_lead_stored_internationally(self):
        lead = Lead.objects.create(phone='+233244000555', first_name='Ama')
        self.assertEqual(find_lead('0244000555'), lead)

    def test_spaces_and_country_code_find_it_too(self):
        lead = Lead.objects.create(phone='+233244000556', first_name='Kofi')
        self.assertEqual(find_lead('233 24 400 0556'), lead)
        self.assertEqual(find_lead('024 400 0556'), lead)

    def test_an_old_lead_stored_locally_is_still_found(self):
        lead = Lead.objects.create(phone='0244000557', first_name='Yaa')
        self.assertEqual(find_lead('+233244000557'), lead)

    def test_nothing_that_is_not_a_number(self):
        self.assertIsNone(find_lead('not a phone'))
        self.assertIsNone(find_lead(''))