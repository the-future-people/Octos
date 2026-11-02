"""
The short registration in the app: personal, and the five kinds of business.
"""

from unittest import mock

from django.test import TestCase

from apps.customers.models import CustomerProfile
from apps.storefront.account_profile import profile_for, register
from apps.storefront.models import Lead


def business(**kw):
    d = {'kind': 'BUSINESS', 'title': 'MR', 'first_name': 'Kwame', 'last_name': 'Asare',
         'business_name': 'Grace Ministries', 'business_type': 'CHURCH',
         'business_phone': '0302 123 456', 'business_email': 'office@grace.org',
         'address': 'Madina, Accra'}
    d.update(kw)
    return d


class RegistrationTests(TestCase):

    def lead(self, phone):
        with mock.patch('apps.storefront.receivers._queue'):
            return Lead.objects.create(phone=phone, first_name='X')

    def test_a_church_is_an_institution_with_its_details(self):
        lead = self.lead('0558000001')
        with mock.patch('apps.storefront.receivers._queue'):
            self.assertIsNone(register(lead, business()))
        c = CustomerProfile.objects.get(pk=lead.customer_id)
        self.assertEqual((c.customer_type, c.institution_subtype), ('INSTITUTION', 'CHURCH'))
        self.assertEqual(c.company_name, 'Grace Ministries')
        self.assertEqual(c.email, 'office@grace.org')
        self.assertTrue(c.secondary_phone)
        p = profile_for(lead)
        self.assertTrue(p['complete'])
        self.assertEqual(p['business_type'], 'CHURCH')

    def test_a_company_is_a_business(self):
        lead = self.lead('0558000002')
        with mock.patch('apps.storefront.receivers._queue'):
            register(lead, business(business_type='COMPANY', business_name='Piwak Ltd'))
        c = CustomerProfile.objects.get(pk=lead.customer_id)
        self.assertEqual((c.customer_type, c.institution_subtype), ('BUSINESS', ''))

    def test_a_business_must_give_type_phone_and_email(self):
        lead = self.lead('0558000003')
        self.assertIn('kind of business', register(lead, business(business_type='')))
        self.assertIn('phone', register(lead, business(business_phone='')))
        self.assertIn('email', register(lead, business(business_email='not-an-email')))

    def test_personal_still_needs_first_and_last_name(self):
        lead = self.lead('0558000004')
        self.assertIn('first and last', register(lead, {'kind': 'PERSONAL', 'title': 'MS', 'gender': 'FEMALE',
                                                         'first_name': 'Esi', 'last_name': ''}))
        with mock.patch('apps.storefront.receivers._queue'):
            self.assertIsNone(register(lead, {'kind': 'PERSONAL', 'title': 'MS', 'gender': 'FEMALE',
                                              'first_name': 'Esi', 'last_name': 'Owusu'}))
        self.assertTrue(profile_for(lead)['complete'])

    def test_a_business_missing_new_details_is_asked_again(self):
        lead = self.lead('0558000005')
        with mock.patch('apps.storefront.receivers._queue'):
            c = CustomerProfile.objects.create(phone='0558000005', customer_type='BUSINESS', title='MR',
                                               first_name='Yaw', last_name='Boateng',
                                               company_name='Old Biz', address='Accra')
        lead.customer = c
        lead.save()
        self.assertFalse(profile_for(lead)['complete'])
