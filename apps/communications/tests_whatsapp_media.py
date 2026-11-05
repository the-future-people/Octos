"""
Keeping customers' files: fetched from Meta (faked here), stored (in
memory here), with type, size and page count; recorded on arrival with
their name and type; and shown to Octos by name and pages.
"""
import io
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase, override_settings
from pypdf import PdfWriter

from apps.communications.assistant import brain
from apps.communications.models import Message
from apps.communications.services import whatsapp_media
from apps.communications.tests import make_conversation
from apps.communications.tests_whatsapp import WebhookTestCase, delivery

MEMORY = {**settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}}


def pdf(pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def meta_serves(content, mime):
    """Fake the two Graph calls: the address for the id, then the bytes."""
    address = MagicMock(status_code=200)
    address.json.return_value = {'url': 'https://lookaside.example/file', 'mime_type': mime,
                                 'file_size': len(content)}
    body = MagicMock(status_code=200, content=content)
    return patch('apps.communications.services.whatsapp_media.requests.get', side_effect=[address, body])


@override_settings(STORAGES=MEMORY, WHATSAPP_ACCESS_TOKEN='test-token')
class KeepMediaTests(TestCase):

    def setUp(self):
        self.conv = make_conversation(None, contact_phone='+233244700701')

    def media_message(self, **fields):
        values = {'message_type': Message.DOCUMENT, 'body': '', 'media_id': 'media-1', **fields}
        return Message.objects.create(conversation=self.conv, direction=Message.INBOUND,
                                      channel=Message.WHATSAPP, **values)

    def test_a_pdf_is_kept_with_its_pages(self):
        msg = self.media_message(media_name='albion-sticker.pdf', media_mime='application/pdf')
        with meta_serves(pdf(3), 'application/pdf'):
            kept = whatsapp_media.fetch(msg.pk)
        self.assertTrue(kept.media_file.name.endswith('albion-sticker.pdf'))
        self.assertEqual((kept.media_pages, kept.media_mime), (3, 'application/pdf'))
        self.assertGreater(kept.media_size, 0)

    def test_an_image_is_one_page(self):
        msg = self.media_message(message_type=Message.IMAGE)
        with meta_serves(b'\x89PNG fake', 'image/png'):
            kept = whatsapp_media.fetch(msg.pk)
        self.assertEqual(kept.media_pages, 1)
        self.assertTrue(kept.media_file.name.endswith('.png'))

    def test_a_file_already_kept_is_not_fetched_again(self):
        msg = self.media_message()
        Message.objects.filter(pk=msg.pk).update(media_file='communications/media/x.pdf')
        with patch('apps.communications.services.whatsapp_media.requests.get') as get:
            whatsapp_media.fetch(msg.pk)
        get.assert_not_called()

    def test_keeping_a_file_never_moves_the_preview(self):
        msg = self.media_message()
        Message.objects.create(conversation=self.conv, direction=Message.INBOUND,
                               channel=Message.WHATSAPP, body='Please 10 copies')
        with meta_serves(pdf(1), 'application/pdf'):
            whatsapp_media.fetch(msg.pk)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.last_message_preview, 'Please 10 copies')

    def test_octos_sees_the_file_by_name_and_pages(self):
        msg = self.media_message(media_name='albion-sticker.pdf', media_pages=2,
                                 media_file='communications/media/albion-sticker.pdf')
        (turn,) = brain._history(self.conv)
        # The file's number is how Octos names it when it prepares an order.
        self.assertIn(f'[sent a document: albion-sticker.pdf, 2 pages, file {msg.pk}]', turn['content'])


class ArrivalTests(WebhookTestCase):

    def test_a_document_arrives_with_its_name_and_type_and_is_queued(self):
        payload = delivery({'from': '233244700702', 'id': 'wamid.DOC1', 'timestamp': '1793900000',
                            'type': 'document',
                            'document': {'id': 'media-9', 'filename': 'flyer.pdf', 'mime_type': 'application/pdf'}})
        with patch('apps.communications.tasks.fetch_whatsapp_media.delay') as keep, \
                self.captureOnCommitCallbacks(execute=True):
            self.deliver(payload)
        msg = Message.objects.get(external_id='wamid.DOC1')
        self.assertEqual((msg.media_name, msg.media_mime, msg.media_id), ('flyer.pdf', 'application/pdf', 'media-9'))
        keep.assert_called_once_with(msg.pk)