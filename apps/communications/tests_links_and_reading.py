"""
Links customers send instead of files, and a chat someone is reading
(27 Nov 2026, Ekd's Adobe links while Khofi had the chat open).
"""
import io
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from pypdf import PdfWriter

from apps.communications.assistant import brain
from apps.communications.models import Message
from apps.communications.services import opened, shared_links
from apps.communications.services.shared_links import LinkError
from apps.communications.tests import make_conversation

MEMORY = {**settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}}
DRIVE = 'https://drive.google.com/file/d/1AbC-dEf_9/view?usp=sharing'


def pdf(pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class DirectUrlTests(TestCase):

    def test_each_place_gives_its_file(self):
        self.assertEqual(shared_links.direct_url(DRIVE),
                         'https://drive.usercontent.google.com/download?id=1AbC-dEf_9&export=download&confirm=t')
        self.assertEqual(shared_links.direct_url('https://docs.google.com/document/d/XyZ/edit'),
                         'https://docs.google.com/document/d/XyZ/export?format=pdf')
        self.assertEqual(shared_links.direct_url('https://docs.google.com/presentation/d/Sl1/edit'),
                         'https://docs.google.com/presentation/d/Sl1/export/pdf')
        self.assertIn('dl=1', shared_links.direct_url('https://www.dropbox.com/s/abc/flyer.pdf?dl=0'))
        self.assertTrue(shared_links.direct_url('https://1drv.ms/b/s!Abc').startswith(
            'https://api.onedrive.com/v1.0/shares/u!'))

    def test_links_only_a_person_can_open(self):
        self.assertIsNone(shared_links.direct_url(
            'https://acrobat.adobe.com/id/urn:aaid:sc:EU:4a1c11d6-32ef-4533-b6de-170888eb0568'))
        self.assertIsNone(shared_links.direct_url('https://www.canva.com/design/DAF/view'))
        self.assertIsNone(shared_links.direct_url('https://example.com/a.pdf'))

    def test_links_in_a_message(self):
        text = f'Please print this {DRIVE} and this {DRIVE} and https://example.com too'
        self.assertEqual(shared_links.links_in(text), [DRIVE])


@override_settings(STORAGES=MEMORY)
class OpeningTests(TestCase):

    def setUp(self):
        self.conv = make_conversation(None, contact_phone='+233557433310', contact_name='Ekd')
        self.said = Message.objects.create(conversation=self.conv, direction=Message.INBOUND,
                                           channel=Message.WHATSAPP, body=f'Print 2 copies {DRIVE}')

    def test_a_link_we_can_open_becomes_their_file(self):
        with patch('apps.communications.tasks.fetch_shared_link.delay') as later, \
                self.captureOnCommitCallbacks(execute=True):
            (held,) = shared_links.open_links(self.conv, self.said)
        later.assert_called_once_with(held.pk)
        self.assertEqual((held.kind, held.media_info['fetching']), (Message.FROM_LINK, True))
        self.assertTrue(brain._still_reading(self.conv.pk))           # its message waits for it
        with patch.object(shared_links, 'download', return_value=(pdf(3), 'application/pdf', 'Notes.pdf')):
            shared_links.fetch(held.pk)
        held.refresh_from_db()
        self.assertTrue(held.media_file)
        self.assertEqual((held.media_name, held.media_pages), ('Notes.pdf', 3))
        self.assertFalse(brain._still_reading(self.conv.pk))

    def test_adobe_is_left_to_the_team(self):
        self.said.body = 'https://acrobat.adobe.com/id/urn:aaid:sc:EU:4a1c11d6'
        self.assertEqual(shared_links.open_links(self.conv, self.said), [])

    def test_a_private_link_says_so(self):
        with patch('apps.communications.tasks.fetch_shared_link.delay'):
            (held,) = shared_links.open_links(self.conv, self.said)
        with patch.object(shared_links, 'download', side_effect=LinkError('private')):
            shared_links.fetch(held.pk)
        held.refresh_from_db()
        self.assertEqual(held.media_info['failed'], 'private')
        self.assertIn("it's private", brain.LINK_FAILED[held.media_info['failed']])
        self.assertFalse(brain._still_reading(self.conv.pk))

    def test_its_file_is_never_the_message_answered(self):
        with patch('apps.communications.tasks.fetch_shared_link.delay'):
            shared_links.open_links(self.conv, self.said)
        last = (self.conv.messages.filter(direction=Message.INBOUND)
                .exclude(kind__in=Message.NOT_TRIGGERS).order_by('-created_at').first())
        self.assertEqual(last, self.said)

    def test_a_sign_in_page_is_private(self):
        page = MagicMock(status_code=200, headers={'Content-Type': 'text/html; charset=utf-8'})
        page.__enter__ = lambda s: s
        page.__exit__ = lambda s, *a: False
        with patch('requests.Session.get', return_value=page), self.assertRaises(LinkError) as caught:
            shared_links.download(DRIVE)
        self.assertEqual(str(caught.exception), 'private')


class BeingReadTests(TestCase):

    def setUp(self):
        cache.clear()
        self.conv = make_conversation(None, contact_phone='+233557433310', contact_name='Ekd')
        self.said = Message.objects.create(conversation=self.conv, direction=Message.INBOUND,
                                           channel=Message.WHATSAPP, body='How much for this?')

    def test_an_open_chat_holds_octos_while_the_message_is_fresh(self):
        self.assertFalse(brain._being_read(self.conv.pk, self.said.pk))
        opened.chat_opened(self.conv, None)
        with patch.object(brain.counter, 'shop_open', return_value=True):
            self.assertTrue(brain._being_read(self.conv.pk, self.said.pk))
            Message.objects.filter(pk=self.said.pk).update(created_at=timezone.now() - timedelta(minutes=4))
            self.assertFalse(brain._being_read(self.conv.pk, self.said.pk))   # nobody answered: Octos does

    def test_out_of_hours_octos_answers(self):
        opened.chat_opened(self.conv, None)
        with patch.object(brain.counter, 'shop_open', return_value=False):
            self.assertFalse(brain._being_read(self.conv.pk, self.said.pk))

    def test_respond_waits_and_looks_again(self):
        opened.chat_opened(self.conv, None)
        with patch.object(brain.counter, 'shop_open', return_value=True), \
                patch('apps.communications.tasks.answer_whatsapp.apply_async') as again, \
                patch.object(brain, '_respond_unmarked') as answer:
            self.assertIsNone(brain.respond(self.conv.pk, self.said.pk))
        answer.assert_not_called()
        self.assertEqual(again.call_args.kwargs['countdown'], brain.READER_RETRY)
