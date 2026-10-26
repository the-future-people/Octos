"""
The counter's customer search: whatever the attendant types, the right
person comes back.

It is the counter's lifeline and had no tests, which is how foreign
numbers could be saved but never found. These pin down every way a
number arrives: the stored international form, the familiar local form,
a number still stored the old way, a second SIM, a number from abroad
written with spaces or with 00.
"""

from django.test import TestCase

from apps.customers.models import CustomerProfile
from apps.customers.selectors import search_customers


def found(query):
    return list(search_customers(query=query, limit=20).values_list('pk', flat=True))


class SearchByNumberTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ama = CustomerProfile.objects.create(
            first_name='Ama', last_name='Mensah', phone='+233244123456',
            secondary_phone='+233551112233', customer_type='INDIVIDUAL',
        )
        cls.old = CustomerProfile.objects.create(
            first_name='Kofi', last_name='Boateng', phone='0209876543', customer_type='INDIVIDUAL',
        )
        cls.alex = CustomerProfile.objects.create(
            first_name='Alex', last_name='Adane', phone='+15145828114', customer_type='INDIVIDUAL',
        )

    def test_the_familiar_local_form(self):
        self.assertIn(self.ama.pk, found('024 412 3456'))
        self.assertIn(self.ama.pk, found('0244123456'))

    def test_the_international_form(self):
        self.assertIn(self.ama.pk, found('+233 24 412 3456'))
        self.assertIn(self.ama.pk, found('233244123456'))

    def test_the_second_sim(self):
        self.assertIn(self.ama.pk, found('055 111 2233'))

    def test_a_number_still_stored_the_old_way(self):
        self.assertIn(self.old.pk, found('+233209876543'))
        self.assertIn(self.old.pk, found('020 987 6543'))

    def test_a_number_from_abroad(self):
        self.assertIn(self.alex.pk, found('+1 514 582 8114'))
        self.assertIn(self.alex.pk, found('001 514 582 8114'))

    def test_only_the_right_person(self):
        self.assertEqual(found('0244123456'), [self.ama.pk])

    def test_a_number_nobody_has(self):
        self.assertNotIn(self.ama.pk, found('0244000000'))
        self.assertNotIn(self.alex.pk, found('0244000000'))


class SearchByNameTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ama = CustomerProfile.objects.create(
            first_name='Ama', last_name='Mensah', phone='+233244123456', customer_type='INDIVIDUAL',
        )
        cls.piwak = CustomerProfile.objects.create(
            first_name='Edward', last_name='Appiah', company_name='Piwak Construction Ltd',
            phone='+233558496250', customer_type='BUSINESS',
        )

    def test_by_surname(self):
        self.assertIn(self.ama.pk, found('Mensah'))

    def test_by_first_name(self):
        self.assertIn(self.ama.pk, found('Ama'))

    def test_by_company_name(self):
        self.assertIn(self.piwak.pk, found('Piwak'))

    def test_a_name_slightly_misspelt(self):
        self.assertIn(self.ama.pk, found('Mensa'))