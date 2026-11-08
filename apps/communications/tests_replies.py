"""
Replying to a particular message, both ways on WhatsApp, and Octos's report
under its own messages (8 Nov 2026).
"""
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.communications.models import Message
from apps.communications.tests import make_conversation, make_org
from apps.communications.tests_whatsapp_outbound import customer_wrote

MEMORY = {**settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}}


class ClientContextTests(TestCase):

    def test_a_reply_carries_whatsapps_quote(self):
        from apps.communications.services import whatsapp_client
        with patch.object(whatsapp_client, '_send', return_value='wamid.R') as sent:
            whatsapp_client.send_text('+233244000111', 'Yes, that one', reply_to='wamid.Q')
        self.assertEqual(sent.call_args[0][1]['context'], {'message_id': 'wamid.Q'})

    def test_a_plain_message_carries_none(self):
        from apps.communications.services import whatsapp_client
        with patch.object(whatsapp_client, '_send', return_value='wamid.R') as sent:
            whatsapp_client.send_text('+233244000111', 'Hello')
        self.assertNotIn('context', sent.call_args[0][1])


@override_settings(STORAGES=MEMORY)
class ReplyViewTests(TestCase):

    def setUp(self):
        make_org()
        self.conv = make_conversation(None, contact_phone='+233244000222')
        customer_wrote(self.conv, timedelta(minutes=3))
        self.asked = self.conv.messages.filter(direction=Message.INBOUND).order_by('-id').first()
        self.api = APIClient()
        self.api.force_authenticate(get_user_model().objects.create_user(
            email='ama@farhat.test', password='x', first_name='Ama', last_name='Mensah'))

    def test_the_reply_remembers_what_it_answers(self):
        response = self.api.post(f'/api/v1/communications/{self.conv.pk}/reply/',
                                 {'body': 'Yes, we print those', 'reply_to': self.asked.pk}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        reply = self.conv.messages.get(body='Yes, we print those')
        self.assertEqual(reply.reply_to_id, self.asked.pk)

    def test_a_message_from_another_chat_is_never_quoted(self):
        other = make_conversation(None, contact_phone='+233244000333')
        customer_wrote(other, timedelta(minutes=3))
        theirs = other.messages.order_by('-id').first()
        self.api.post(f'/api/v1/communications/{self.conv.pk}/reply/',
                      {'body': 'Hello', 'reply_to': theirs.pk}, format='json')
        self.assertIsNone(self.conv.messages.get(body='Hello').reply_to_id)


class ReportTests(TestCase):

    def test_octos_message_carries_its_report(self):
        from apps.communications.models import AssistantRun
        from apps.communications.services.reports import octos_report
        make_org()
        conv = make_conversation(None, contact_phone='+233244000444')
        AssistantRun.objects.create(conversation=conv, mode='live', decision='REPLIED', reply='A3 colour is GHS 5.00',
                                    tool_calls=[{'name': 'find_services'}, {'name': 'quote', 'result': {'total': 'GHS 5.00'}}])
        said = Message.objects.create(conversation=conv, direction=Message.OUTBOUND, channel=conv.channel,
                                      body='A3 colour is GHS 5.00')
        report = octos_report(said)
        self.assertEqual(report['summary'], 'Looked up the catalogue, Priced it')
        self.assertIn(['ok', 'Priced it: GHS 5.00'], report['steps'])

    def test_staff_messages_have_no_report(self):
        from apps.communications.services.reports import octos_report
        make_org()
        conv = make_conversation(None, contact_phone='+233244000555')
        staff = get_user_model().objects.create_user(email='s@farhat.test', password='x', first_name='S', last_name='A')
        said = Message.objects.create(conversation=conv, direction=Message.OUTBOUND, channel=conv.channel,
                                      body='Hello', sent_by=staff)
        self.assertIsNone(octos_report(said))
