"""
Chat files are served through Octos, to those who may see the chat (8 Nov 2026).
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.communications.models import Message
from apps.communications.tests import make_conversation, make_org

MEMORY = {**settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}}


@override_settings(STORAGES=MEMORY)
class MessageFileTests(TestCase):

    def setUp(self):
        make_org()
        self.conv = make_conversation(None, contact_phone='+233244000444')
        self.msg = Message.objects.create(conversation=self.conv, direction=Message.INBOUND,
                                          channel=self.conv.channel, body='notes.pdf',
                                          message_type=Message.DOCUMENT, media_name='notes.pdf',
                                          media_mime='application/pdf')
        self.msg.media_file.save('notes.pdf', ContentFile(b'%PDF-1.4 court notes'))
        self.api = APIClient()
        self.api.force_authenticate(get_user_model().objects.create_user(
            email='staff@farhat.test', password='x', first_name='Esi', last_name='Ofori'))

    def url(self, pk):
        return f'/api/v1/communications/messages/{pk}/file/'

    def test_the_file_comes_through_octos(self):
        response = self.api.get(self.url(self.msg.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 court notes')
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('inline', response['Content-Disposition'])

    def test_download_saves_it_with_its_name(self):
        response = self.api.get(self.url(self.msg.pk) + '?download=1')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('notes.pdf', response['Content-Disposition'])

    def test_nobody_signed_out_gets_it(self):
        self.assertIn(APIClient().get(self.url(self.msg.pk)).status_code, (401, 403))

    def test_a_message_without_a_file_is_not_found(self):
        bare = Message.objects.create(conversation=self.conv, direction=Message.INBOUND,
                                      channel=self.conv.channel, body='hello')
        self.assertEqual(self.api.get(self.url(bare.pk)).status_code, 404)
