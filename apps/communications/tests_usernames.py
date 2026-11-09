"""
WhatsApp usernames (9 Nov 2026): a customer may arrive with no phone number.
"""
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase, SimpleTestCase, override_settings

from apps.communications.models import Conversation, Message
from apps.communications.tests import make_org


class UsernameMessagesTests(TestCase):

    def setUp(self):
        make_org()

    def receive(self, message, who):
        from apps.communications.services.whatsapp_inbound import _receive
        with patch('apps.communications.services.whatsapp_inbound.wake_octos'):
            with transaction.atomic():
                return _receive(message, who.get('name', ''), who)

    def test_a_username_customer_is_recorded_without_a_phone(self):
        who = {'name': 'Priscilla', 'username': 'pearlspec6', 'user_id': 'GH.1114480144784115'}
        self.assertTrue(self.receive({'id': 'wamid.U1', 'from_user_id': 'GH.1114480144784115',
                                      'type': 'text', 'text': {'body': 'Good morning'}}, who))
        chat = Conversation.objects.get(contact_user_id='GH.1114480144784115')
        self.assertEqual((chat.contact_phone, chat.contact_username), ('', 'pearlspec6'))
        self.assertEqual(chat.messages.get().body, 'Good morning')

    def test_two_customers_with_no_number_never_clash(self):
        for n, uid in enumerate(('GH.111', 'GH.222')):
            self.receive({'id': f'wamid.C{n}', 'from_user_id': uid, 'type': 'text', 'text': {'body': 'Hi'}},
                         {'name': f'C{n}', 'user_id': uid})
        self.assertEqual(Conversation.objects.filter(contact_phone='').count(), 2)

    def test_the_same_person_keeps_one_chat_after_hiding_their_number(self):
        self.receive({'id': 'wamid.P1', 'from': '233244000999', 'type': 'text', 'text': {'body': 'Hi'}},
                     {'name': 'Kofi', 'user_id': 'GH.999'})
        self.receive({'id': 'wamid.P2', 'from_user_id': 'GH.999', 'type': 'text', 'text': {'body': 'Again'}},
                     {'name': 'Kofi', 'user_id': 'GH.999'})
        self.assertEqual(Conversation.objects.filter(contact_user_id='GH.999').count(), 1)
        self.assertEqual(Conversation.objects.get(contact_user_id='GH.999').messages.count(), 2)


@override_settings(WHATSAPP_ACCESS_TOKEN='t', WHATSAPP_PHONE_NUMBER_ID='1')
class SendingToAUsernameTests(SimpleTestCase):

    def test_a_user_id_goes_in_recipient(self):
        from apps.communications.services import whatsapp_client
        with patch.object(whatsapp_client.requests, 'post') as post:
            post.return_value.json.return_value = {'messages': [{'id': 'wamid.S'}]}
            post.return_value.status_code = 200
            try:
                whatsapp_client.send_text('GH.1114480144784115', 'Hello')
            except Exception:
                pass
        sent = post.call_args.kwargs['json']
        self.assertEqual(sent.get('recipient'), 'GH.1114480144784115')
        self.assertNotIn('to', sent)
