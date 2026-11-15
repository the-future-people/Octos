"""
Files are ready first, read after (15 Nov 2026).

A customer's file is saved and openable, and the inbox told, before it is
measured: a Word file's conversion to PDF took up to 90 seconds before
anyone could open it. Octos waits while a file is still being read.

Run: docker compose exec web python manage.py test apps.communications.tests_files_fast -t .
"""
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.communications.models import Message
from apps.communications.services import whatsapp_media
from apps.communications.tests import make_conversation


class ReadyFirstTests(TestCase):

    def setUp(self):
        self.conv = make_conversation(None, contact_phone='+233244000611')
        self.msg = Message.objects.create(
            conversation=self.conv, direction=Message.INBOUND, channel=Message.WHATSAPP,
            message_type=Message.DOCUMENT, media_id='m-77', media_name='cv.docx',
            media_mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

    def test_the_file_is_openable_before_it_is_measured(self):
        seen = {}

        def measuring(content, name, mime):
            during = Message.objects.get(pk=self.msg.pk)
            seen['file'] = bool(during.media_file)
            seen['info'] = during.media_info
            return {'page_count': 2, 'paper': 'A4'}, 2

        with patch.object(whatsapp_media, 'download', return_value=(b'word bytes', '')), \
                patch.object(whatsapp_media, '_measure', side_effect=measuring):
            whatsapp_media.fetch(self.msg.pk)
        self.assertTrue(seen['file'])
        self.assertEqual(seen['info'], {'measuring': True})
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.media_pages, 2)
        self.assertEqual(self.msg.media_info, {'page_count': 2, 'paper': 'A4'})

    def test_a_failed_measurement_never_leaves_the_file_measuring(self):
        with patch.object(whatsapp_media, 'download', return_value=(b'word bytes', '')), \
                patch.object(whatsapp_media, '_measure', side_effect=RuntimeError('broken file')):
            with self.assertRaises(RuntimeError):
                whatsapp_media.fetch(self.msg.pk)
        self.msg.refresh_from_db()
        self.assertTrue(self.msg.media_file)
        self.assertNotIn('measuring', self.msg.media_info or {})


@override_settings(ANTHROPIC_API_KEY='test-key', OCTOS_ASSISTANT_MODE='live')
class OctosWaitsForTheFileTests(TestCase):

    def test_octos_waits_while_a_file_is_being_read(self):
        from apps.communications.assistant import brain
        conv = make_conversation(None, contact_phone='+233244000612')
        msg = Message.objects.create(
            conversation=conv, direction=Message.INBOUND, channel=Message.WHATSAPP,
            message_type=Message.DOCUMENT, media_id='m-78', media_file='communications/media/x.pdf',
            media_info={'measuring': True})
        with patch('apps.communications.tasks.answer_whatsapp.apply_async') as again, \
                patch('anthropic.Anthropic') as model:
            self.assertIsNone(brain.respond(conv.pk, msg.pk))
        again.assert_called_once_with((conv.pk, msg.pk), countdown=brain.RETRY_SECONDS)
        model.assert_not_called()
