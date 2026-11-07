"""
Titles in Octos's greeting (7 Nov 2026): "Good afternoon, Mr. Muntaka".
"""
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from apps.communications.assistant.prompt import _customer_line, _titled
from apps.communications.tests import make_conversation, make_org


def person(title='', first='Ibrahim', last='Muntaka', other=''):
    return SimpleNamespace(title=title, first_name=first, last_name=last, title_other=other)


class TitledTests(SimpleTestCase):

    def test_a_title_and_a_surname(self):
        self.assertEqual(_titled(person('MR')), 'Mr. Muntaka')
        self.assertEqual(_titled(person('DR', last='Asante')), 'Dr. Asante')
        self.assertEqual(_titled(person('MADAM', last='Owusu')), 'Madam Owusu')

    def test_another_title_as_the_record_spells_it(self):
        self.assertEqual(_titled(person('OTHER', other='Hon.')), 'Hon. Muntaka')

    def test_no_title_no_surname_or_esq_is_not_titled(self):
        self.assertEqual(_titled(person('')), '')
        self.assertEqual(_titled(person('MR', last='')), '')
        self.assertEqual(_titled(person('ESQ')), '')


class GreetingTests(TestCase):

    def test_octos_is_told_to_greet_them_with_their_title(self):
        from apps.customers.models import CustomerProfile
        make_org()
        customer = CustomerProfile.objects.create(phone='+233244000777', title='MR', first_name='Ibrahim',
                                                  last_name='Muntaka', customer_type='INDIVIDUAL')
        conversation = make_conversation(None, contact_phone='+233244000777')
        conversation.customer = customer
        conversation.save()
        self.assertIn('talking to Mr. Muntaka', _customer_line(conversation))

    def test_without_a_title_it_is_the_first_name(self):
        from apps.customers.models import CustomerProfile
        make_org()
        customer = CustomerProfile.objects.create(phone='+233244000776', first_name='Ama', last_name='Owusu',
                                                  customer_type='INDIVIDUAL')
        conversation = make_conversation(None, contact_phone='+233244000776')
        conversation.customer = customer
        conversation.save()
        self.assertIn('talking to Ama,', _customer_line(conversation))
