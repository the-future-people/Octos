"""
One "at the counter" (Layer 1, Step 1.3, merged 11 Nov 2026).

The QR message starts the counter visit the moment it arrives; the attendant's
tap starts it too; both reach the spine; an outcome ends the quiet early; and
files someone already handled get no reply.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.communications.assistant import brain, counter
from apps.communications.models import Conversation, Message
from apps.communications.services.whatsapp_inbound import _receive
from apps.spine import kinds
from apps.spine.models import Event, Visit
from apps.spine.obligations import FILES, REPLY, files_handled, ledger
from apps.spine.recorder import record


def _wa(wamid, body='', file=False):
    if file:
        return {'id': wamid, 'from': '233244123456', 'type': 'document',
                'document': {'id': 'media-1', 'filename': 'cv.pdf', 'mime_type': 'application/pdf'}}
    return {'id': wamid, 'from': '233244123456', 'type': 'text', 'text': {'body': body}}


@override_settings(OCTOS_ASSISTANT_MODE='off', ANTHROPIC_API_KEY='test')
@patch('apps.communications.services.whatsapp_inbound._keep_media')
@patch('apps.communications.assistant.counter.shop_open', return_value=True)
class CounterArrivalTests(TestCase):
    def test_the_qr_message_starts_the_visit_on_arrival(self, _open, _media):
        _receive(_wa('wamid.Q1', "Hi, I'm at the Westland counter"), 'Priscilla')
        chat = Conversation.objects.get()
        self.assertTrue(counter.in_visit(chat))
        self.assertTrue(Event.objects.filter(kind=kinds.PRESENCE_COUNTER).exists())
        self.assertEqual(Visit.objects.get().presence, Visit.AT_COUNTER)

    def test_a_photo_seconds_after_the_qr_gets_no_stock_reply(self, _open, _media):
        # Priscilla, 9 Nov: the QR's own run is skipped for the newer photo,
        # and the visit must already exist when the photo's run looks.
        _receive(_wa('wamid.Q2', "Hi, I'm at the Westland counter"), 'Priscilla')
        _receive(_wa('wamid.P2', file=True), 'Priscilla')
        chat = Conversation.objects.get()
        photo = Message.objects.get(external_id='wamid.P2')
        said, why = counter.step(chat, photo, timezone.now())
        self.assertIsNone(said)
        self.assertIn('attendant', why)

    def test_an_ordinary_message_is_not_a_counter_visit(self, _open, _media):
        _receive(_wa('wamid.O1', 'How much is A4 colour?'), 'Ama')
        self.assertFalse(counter.in_visit(Conversation.objects.get()))
        self.assertFalse(Event.objects.filter(kind=kinds.PRESENCE_COUNTER).exists())

    def test_an_outcome_ends_the_quiet_early(self, _open, _media):
        _receive(_wa('wamid.Q3', "Hi, I'm at the Westland counter"), 'Ama')
        chat = Conversation.objects.get()
        record(kinds.JOB_CREATED, actor=Event.STAFF, conversation=chat)
        chat.refresh_from_db()
        self.assertFalse(counter.in_visit(chat))
        self.assertEqual(Visit.objects.get().outcome, 'JOB_CREATED')

    def test_files_made_into_a_job_get_no_reply(self, _open, _media):
        _receive(_wa('wamid.F1', file=True), 'Ama')
        chat = Conversation.objects.get()
        record(kinds.JOB_CREATED, actor=Event.STAFF, conversation=chat)
        trigger = Message.objects.get(external_id='wamid.F1')
        chat.refresh_from_db()
        self.assertEqual(brain._silence(chat, trigger, timezone.now()), 'the files were already handled')


class LedgerTests(TestCase):
    def setUp(self):
        self.chat = Conversation.objects.create(
            branch=None, contact_phone='+233244123457', channel=Conversation.WHATSAPP)

    def test_files_open_until_handled(self):
        record(kinds.MESSAGE_RECEIVED, conversation=self.chat, key='wa:L1', payload={'has_file': True})
        visit = Visit.objects.get()
        self.assertFalse(files_handled(visit))
        record(kinds.COUNTER_CLAIMED, conversation=self.chat)
        self.assertTrue(files_handled(visit))

    def test_a_question_is_open_until_someone_answers(self):
        record(kinds.MESSAGE_RECEIVED, conversation=self.chat, key='wa:L2', payload={'has_file': False})
        visit = Visit.objects.get()
        [question] = ledger(visit)
        self.assertEqual(question.what, REPLY)
        self.assertTrue(question.open)
        record(kinds.MESSAGE_SENT, actor=Event.OCTOS, conversation=self.chat, payload={'system_kind': ''})
        [question] = ledger(visit)
        self.assertFalse(question.open)

    def test_the_owner_is_the_attendant_at_the_counter(self):
        record(kinds.PRESENCE_COUNTER, conversation=self.chat)
        record(kinds.MESSAGE_RECEIVED, conversation=self.chat, key='wa:L3', payload={'has_file': True})
        visit = Visit.objects.get()
        [files] = ledger(visit)
        self.assertEqual((files.what, files.owner), (FILES, 'attendant'))
