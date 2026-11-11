"""
Serving at the counter, and the obligations ledger (Layer 1, Step 1.3, 11 Nov 2026).
"""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.communications.assistant import brain
from apps.communications.models import Conversation, Message
from apps.communications.services import handover
from apps.spine import kinds
from apps.spine.models import Event, Visit
from apps.spine.obligations import FILES, REPLY, files_handled, ledger
from apps.spine.recorder import record


@override_settings(OCTOS_ASSISTANT_MODE='off', ANTHROPIC_API_KEY='test')
class CounterTests(TestCase):
    def setUp(self):
        self.chat = Conversation.objects.create(
            branch=None, contact_phone='+233244123456', channel=Conversation.WHATSAPP)

    def _inbound(self, wamid, media=False, minutes_ago=0):
        message = Message.objects.create(
            conversation=self.chat, direction=Message.INBOUND, channel=Message.WHATSAPP,
            message_type=Message.DOCUMENT if media else Message.TEXT,
            body='' if media else 'How much?', external_id=wamid, media_id='m1' if media else '')
        if minutes_ago:
            Message.objects.filter(pk=message.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
            message.refresh_from_db()
        record(kinds.MESSAGE_RECEIVED, actor=Event.CUSTOMER, conversation=self.chat,
               key=f'wa:{wamid}', payload={'message_id': message.pk, 'has_file': media})
        return message

    def test_serving_at_the_counter_quiets_octos_and_opens_a_counter_visit(self):
        handover.serve_at_counter(self.chat)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.handled_by, Conversation.COUNTER)
        self.assertTrue(Event.objects.filter(kind=kinds.COUNTER_CLAIMED).exists())
        self.assertEqual(Visit.objects.get().presence, Visit.AT_COUNTER)

    def test_nobody_is_reminded_or_taken_back_at_the_counter(self):
        self._inbound('wamid.C1', minutes_ago=45)
        handover.serve_at_counter(self.chat)
        self.assertEqual(handover.watch(), (0, 0))
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.handled_by, Conversation.COUNTER)

    def test_the_visit_ending_returns_the_chat_to_octos_quietly(self):
        handover.serve_at_counter(self.chat)
        record(kinds.JOB_CREATED, actor=Event.STAFF, conversation=self.chat)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.handled_by, Conversation.OCTOS)
        # Nothing was said to the customer: only internal notes were written
        self.assertFalse(self.chat.messages.filter(is_internal_note=False,
                                                   direction=Message.OUTBOUND).exists())

    def test_octos_is_silent_while_someone_serves_at_the_counter(self):
        trigger = self._inbound('wamid.C2')
        handover.serve_at_counter(self.chat)
        self.chat.refresh_from_db()
        self.assertIn('counter', brain._silence(self.chat, trigger, timezone.now()))

    def test_files_already_turned_into_a_job_get_no_reply(self):
        trigger = self._inbound('wamid.F1', media=True)
        record(kinds.JOB_CREATED, actor=Event.STAFF, conversation=self.chat)
        self.chat.refresh_from_db()
        self.assertEqual(brain._silence(self.chat, trigger, timezone.now()),
                         'the files were already handled')

    def test_unhandled_files_are_still_octos_to_consider(self):
        trigger = self._inbound('wamid.F2', media=True)
        self.assertIsNone(brain._silence(self.chat, trigger, timezone.now()))


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
        record(kinds.MESSAGE_RECEIVED, conversation=self.chat, key='wa:L3', payload={'has_file': True})
        visit = Visit.objects.get()
        [files] = ledger(visit, handled_by='COUNTER')
        self.assertEqual((files.what, files.owner), (FILES, 'attendant'))
