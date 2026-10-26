"""App accounts: the counter's customers are welcomed back; new numbers register once, never twice."""

from django.test import TestCase

from apps.customers.models import CustomerProfile
from apps.storefront.account_profile import profile_for, register
from apps.storefront.models import Lead


class ProfileTests(TestCase):

    def test_a_counter_customer_is_recognised_by_number(self):
        eric = CustomerProfile.objects.create(title='MR', first_name='Eric', last_name='Nortey', gender='MALE',
                                              phone='+233248370473', customer_type='INDIVIDUAL')
        lead = Lead.objects.create(phone='+233248370473', first_name='Eric')
        p = profile_for(lead)
        self.assertTrue(p['complete'])
        lead.refresh_from_db()
        self.assertEqual(lead.customer_id, eric.pk)

    def test_a_new_number_needs_the_short_registration(self):
        lead = Lead.objects.create(phone='+233244000111', first_name='Ama')
        self.assertFalse(profile_for(lead)['complete'])

    def test_registering_makes_one_customer_and_links_it(self):
        lead = Lead.objects.create(phone='+233244000111', first_name='Ama')
        problem = register(lead, {'kind': 'PERSONAL', 'title': 'MS', 'gender': 'FEMALE',
                                  'first_name': 'Ama', 'last_name': 'Mensah'})
        self.assertIsNone(problem)
        lead.refresh_from_db()
        self.assertEqual(lead.customer.last_name, 'Mensah')
        self.assertTrue(profile_for(lead)['complete'])
        self.assertEqual(CustomerProfile.objects.filter(phone='+233244000111').count(), 1)

    def test_an_incomplete_counter_record_is_completed_not_duplicated(self):
        old = CustomerProfile.objects.create(first_name='Kofi', phone='0209876543', customer_type='INDIVIDUAL')
        lead = Lead.objects.create(phone='+233209876543', first_name='Kofi')
        self.assertFalse(profile_for(lead)['complete'])
        register(lead, {'kind': 'PERSONAL', 'title': 'MR', 'gender': 'MALE', 'first_name': 'Kofi', 'last_name': 'Boateng'})
        old.refresh_from_db()
        self.assertEqual(old.last_name, 'Boateng')
        self.assertEqual(CustomerProfile.objects.count(), 1)

    def test_a_business_needs_its_name_and_address(self):
        lead = Lead.objects.create(phone='+233558496250', first_name='Edward')
        self.assertIn('business', register(lead, {'kind': 'BUSINESS', 'title': 'MR', 'first_name': 'Edward',
                                                  'last_name': 'Appiah'}).lower())
        self.assertIsNone(register(lead, {'kind': 'BUSINESS', 'title': 'MR', 'first_name': 'Edward', 'last_name': 'Appiah',
                                          'business_name': 'Piwak Construction Ltd', 'address': 'Westland, Accra'}))
        lead.refresh_from_db()
        self.assertEqual(lead.customer.customer_type, 'BUSINESS')
        self.assertEqual(profile_for(lead)['kind'], 'BUSINESS')

    def test_nothing_is_saved_without_a_title(self):
        lead = Lead.objects.create(phone='+233244000222', first_name='Yaw')
        self.assertIsNotNone(register(lead, {'kind': 'PERSONAL', 'gender': 'MALE', 'first_name': 'Yaw', 'last_name': 'Asante'}))
        self.assertFalse(CustomerProfile.objects.filter(phone='+233244000222').exists())