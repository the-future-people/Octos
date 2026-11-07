"""
The inbox (7 Nov 2026): replies carry files, notes keep them for staff, and
a chat can be started with an approved WhatsApp message.
"""
import io
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.communications.models import Conversation, Message
from apps.communications.tests import make_conversation, make_org
from apps.communications.tests_whatsapp_outbound import customer_wrote

MEMORY = {**settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}}


def jpeg():
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (40, 30), (200, 40, 40)).save(out, 'JPEG')
    return out.getvalue()


@override_settings(STORAGES=MEMORY)
class InboxFilesTests(TestCase):

    def setUp(self):
        make_org()
        self.user = get_user_model().objects.create_user(
            email='sharon@farhat.test', password='x', first_name='Sharon', last_name='Asare')
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.conv = make_conversation(None, contact_phone='+233244000555')
        customer_wrote(self.conv, timedelta(minutes=5))

    def reply(self, files, **data):
        return self.api.post(f'/api/v1/communications/{self.conv.pk}/reply/',
                             {'attachments': files, **data}, format='multipart')

    def test_a_document_is_sent_as_a_document(self):
        pdf = SimpleUploadedFile('price-list.pdf', b'%PDF-1.4 list', content_type='application/pdf')
        response = self.reply([pdf], body='Here is our price list')
        self.assertEqual(response.status_code, 201, response.content)
        sent = self.conv.messages.filter(message_type=Message.DOCUMENT, is_internal_note=False)
        self.assertEqual(sent.get().media_mime, 'application/pdf')
        # The text goes after the file, as its own message.
        self.assertTrue(self.conv.messages.filter(body='Here is our price list').exists())

    def test_a_photo_is_sent_as_a_photo(self):
        photo = SimpleUploadedFile('proof.jpg', jpeg(), content_type='image/jpeg')
        response = self.reply([photo])
        self.assertEqual(response.status_code, 201, response.content)
        sent = self.conv.messages.get(message_type=Message.IMAGE)
        self.assertTrue(sent.media_file.name.endswith('.png'))

    def test_a_note_keeps_the_file_for_staff_and_sends_nothing(self):
        pdf = SimpleUploadedFile('approval.pdf', b'%PDF-1.4 ok', content_type='application/pdf')
        response = self.reply([pdf], body='Approved by phone', is_internal_note='true')
        self.assertEqual(response.status_code, 201, response.content)
        note = self.conv.messages.get(is_internal_note=True)
        self.assertEqual((note.body, note.media_name), ('Approved by phone', 'approval.pdf'))
        self.assertFalse(self.conv.messages.filter(is_internal_note=False, direction=Message.OUTBOUND).exists())

    def test_a_file_over_16_mb_is_refused_plainly(self):
        big = SimpleUploadedFile('huge.pdf', b'0' * (16 * 1024 * 1024 + 1), content_type='application/pdf')
        response = self.reply([big])
        self.assertEqual(response.status_code, 400)
        self.assertIn('over 16 MB', response.json()['detail'])


class StartChatTests(TestCase):

    def setUp(self):
        make_org()
        self.user = get_user_model().objects.create_user(
            email='bm@farhat.test', password='x', first_name='Ama', last_name='Mensah')
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_a_chat_starts_with_an_approved_message(self):
        with patch('apps.communications.services.whatsapp_client.send_template', return_value='wamid.T1') as sent:
            response = self.api.post('/api/v1/communications/start/', {
                'phone': '024 400 0776', 'name': 'Ama Owusu', 'template': 'order_ready',
                'params': ['Ama', 'FP-WLB-05812']}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(sent.call_args.kwargs['params'], ['Ama', 'FP-WLB-05812'])
        conversation = Conversation.objects.get(pk=response.json()['conversation'])
        self.assertEqual(conversation.contact_phone, '+233244000776')
        message = conversation.messages.get()
        self.assertIn('your order FP-WLB-05812 is ready', message.body)

    def test_only_approved_messages_and_every_blank_filled(self):
        self.assertEqual(self.api.post('/api/v1/communications/start/', {
            'phone': '0244000776', 'template': 'anything', 'params': []}, format='json').status_code, 400)
        self.assertEqual(self.api.post('/api/v1/communications/start/', {
            'phone': '0244000776', 'template': 'order_ready', 'params': ['Ama', '']}, format='json').status_code, 400)
