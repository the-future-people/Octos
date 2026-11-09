"""
Photos sent together, as one PDF to print once (9 Nov 2026).
"""
import io

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.communications.models import Message
from apps.communications.tests import make_conversation, make_org

MEMORY = {**settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}}


def photo(width, height):
    out = io.BytesIO()
    Image.new('RGB', (width, height), (200, 120, 80)).save(out, 'JPEG')
    return ContentFile(out.getvalue(), name='photo.jpg')


@override_settings(STORAGES=MEMORY)
class PhotosPdfTests(TestCase):

    def setUp(self):
        make_org()
        self.conv = make_conversation(None, contact_phone='+233244000999')
        self.api = APIClient()
        self.api.force_authenticate(get_user_model().objects.create_user(
            email='album@farhat.test', password='x', first_name='Esi', last_name='Ofori'))

    def sent(self, width, height):
        m = Message(conversation=self.conv, direction=Message.INBOUND, channel=self.conv.channel,
                    message_type=Message.IMAGE, media_mime='image/jpeg', media_name='photo.jpg')
        m.media_file.save('photo.jpg', photo(width, height), save=False)
        m.save()
        return m

    def test_photos_become_one_pdf(self):
        ids = [self.sent(800, 1200).pk, self.sent(1600, 900).pk, self.sent(600, 600).pk]
        response = self.api.post(f'/api/v1/communications/{self.conv.pk}/photos-pdf/', {'messages': ids}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn('3 photos.pdf', response['Content-Disposition'])

    def test_photos_from_another_chat_are_left_out(self):
        other = make_conversation(None, contact_phone='+233244000998')
        m = Message(conversation=other, direction=Message.INBOUND, channel=other.channel,
                    message_type=Message.IMAGE, media_mime='image/jpeg', media_name='x.jpg')
        m.media_file.save('x.jpg', photo(100, 100), save=False)
        m.save()
        response = self.api.post(f'/api/v1/communications/{self.conv.pk}/photos-pdf/', {'messages': [m.pk]}, format='json')
        self.assertEqual(response.status_code, 400)
