"""
Octos fixes from the 14 Nov 2026 review of a week of chats.

The customer always speaks last when Octos asks the model (Steve); one run
at a time per chat (Tailee's double hand-over); a hand-over counts as
answered; a reaction is kept but never answered and opens no visit
(Henry); a chat a person still holds goes back to Octos when the visit
goes quiet (the stuck chats).
"""
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.communications.assistant import brain
from apps.communications.models import AssistantRun, Conversation, Message
from apps.communications.services import handover
from apps.communications.services.whatsapp_inbound import _receive
from apps.spine import kinds, visits
from apps.spine.models import Event, Visit
from apps.spine.recorder import record


def _chat(phone='+233244123460'):
    return Conversation.objects.create(branch=None, contact_phone=phone, channel=Conversation.WHATSAPP)


def _said(chat, body, inbound=True, kind=''):
    return Message.objects.create(
        conversation=chat, direction=Message.INBOUND if inbound else Message.OUTBOUND,
        channel=Message.WHATSAPP, body=body, kind=kind)


class CustomerSpeaksLastTests(TestCase):
    def test_a_welcome_after_the_customer_comes_off_the_end(self):
        chat = _chat()
        _said(chat, 'My CV, 1 copy')
        _said(chat, 'Hi Steve, welcome to Farhat Printing Press!', inbound=False, kind='welcome')
        turns, since = brain._split_trailing(brain._history(chat))
        self.assertEqual(turns[-1]['role'], 'user')
        self.assertIn('welcome', since)

    def test_nothing_after_the_customer_leaves_the_history_alone(self):
        chat = _chat()
        _said(chat, 'How much is A4 colour?')
        turns, since = brain._split_trailing(brain._history(chat))
        self.assertEqual([t['role'] for t in turns], ['user'])
        self.assertEqual(since, '')


class OneRunAtATimeTests(TestCase):
    def tearDown(self):
        cache.clear()

    def test_a_second_run_waits_and_tries_again(self):
        chat = _chat()
        cache.add(f'octos_run:{chat.pk}', True, 60)
        with patch('apps.communications.tasks.answer_whatsapp.apply_async') as later:
            self.assertIsNone(brain.respond(chat.pk, 77))
        later.assert_called_once_with((chat.pk, 77), countdown=brain.RETRY_SECONDS)


@override_settings(ANTHROPIC_API_KEY='test')
class AnsweredTests(TestCase):
    def test_a_hand_over_counts_as_answered(self):
        chat = _chat()
        question = _said(chat, 'Do you print 8 x 10?')
        AssistantRun.objects.create(conversation=chat, trigger=question, mode='live',
                                    model='test', decision=AssistantRun.HANDED_OVER)
        self.assertEqual(brain._silence(chat, question, timezone.now()), 'already answered')

    def test_a_reaction_after_a_question_does_not_hide_it(self):
        chat = _chat()
        question = _said(chat, 'How much is A4 colour?')
        _said(chat, 'Reacted 👍', kind=Message.REACTION)
        self.assertIsNone(brain._silence(chat, question, timezone.now()))


@override_settings(OCTOS_ASSISTANT_MODE='off')
class ReactionTests(TestCase):
    def test_a_reaction_is_kept_but_opens_no_visit(self):
        _receive({'id': 'wamid.R1', 'from': '233244123461', 'type': 'reaction',
                  'reaction': {'message_id': 'wamid.X', 'emoji': '👍'}}, 'Henry')
        message = Message.objects.get(external_id='wamid.R1')
        self.assertEqual(message.kind, Message.REACTION)
        self.assertTrue(Event.objects.filter(kind=kinds.MESSAGE_REACTED).exists())
        self.assertFalse(Event.objects.filter(kind=kinds.MESSAGE_RECEIVED).exists())
        self.assertFalse(Visit.objects.exists())

    def test_a_reaction_is_not_a_customer_waiting(self):
        chat = _chat()
        _said(chat, 'Here is your scan', inbound=False)
        _said(chat, 'Reacted 👍', kind=Message.REACTION)
        self.assertIsNone(handover.waiting_since(chat))


class ReleaseAfterVisitTests(TestCase):
    def _held_chat_with_old_visit(self):
        chat = _chat()
        record(kinds.MESSAGE_RECEIVED, conversation=chat, key='wa:OLD1',
               occurred_at=timezone.now() - timedelta(hours=3), payload={'has_file': False})
        Conversation.objects.filter(pk=chat.pk).update(handled_by=Conversation.STAFF)
        return chat

    def test_a_quiet_visit_gives_the_chat_back_to_octos(self):
        chat = self._held_chat_with_old_visit()
        visits.close_quiet()
        chat.refresh_from_db()
        self.assertEqual(chat.handled_by, Conversation.OCTOS)
        self.assertTrue(Event.objects.filter(kind=kinds.OCTOS_TOOK_BACK, conversation=chat).exists())

    def test_a_job_created_leaves_the_person_in_charge(self):
        chat = _chat()
        record(kinds.MESSAGE_RECEIVED, conversation=chat, key='wa:NEW1', payload={'has_file': False})
        Conversation.objects.filter(pk=chat.pk).update(handled_by=Conversation.STAFF)
        record(kinds.JOB_CREATED, actor=Event.STAFF, conversation=chat)
        chat.refresh_from_db()
        self.assertEqual(chat.handled_by, Conversation.STAFF)