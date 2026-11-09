"""
Who a chat belongs to, for customers with a WhatsApp username (9 Nov 2026).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.communications.models import Conversation
from apps.communications.services import identity
from apps.communications.tests import make_org
from apps.customers.models import CustomerProfile


class IdentityTests(TestCase):

    def setUp(self):
        make_org()
        self.chat = Conversation.objects.create(branch=None, contact_phone='', channel=Conversation.WHATSAPP,
                                                contact_user_id='GH.555', contact_username='pearlspec6')

    def test_their_number_finds_their_record(self):
        ama = CustomerProfile.objects.create(phone='+233244000777', first_name='Ama', last_name='Owusu',
                                             customer_type='INDIVIDUAL')
        self.assertEqual(identity.match_phone(self.chat, '+233244000777'), ama)
        self.chat.refresh_from_db()
        self.assertEqual((self.chat.customer_id, self.chat.contact_phone), (ama.pk, '+233244000777'))

    def test_no_record_then_a_name_starts_one(self):
        self.assertIsNone(identity.match_phone(self.chat, '+233244000778'))
        customer = identity.register_from_chat(self.chat, 'Priscilla')
        self.assertEqual((customer.first_name, customer.phone), ('Priscilla', '+233244000778'))
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.customer_id, customer.pk)

    def test_staff_can_link_a_chat_to_a_customer(self):
        kofi = CustomerProfile.objects.create(phone='+233244000779', first_name='Kofi', customer_type='INDIVIDUAL')
        api = APIClient()
        api.force_authenticate(get_user_model().objects.create_user(
            email='link@farhat.test', password='x', first_name='Esi', last_name='Ofori'))
        response = api.post(f'/api/v1/communications/{self.chat.pk}/link-customer/', {'customer': kofi.pk}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.chat.refresh_from_db()
        self.assertEqual((self.chat.customer_id, self.chat.contact_phone), (kofi.pk, '+233244000779'))
