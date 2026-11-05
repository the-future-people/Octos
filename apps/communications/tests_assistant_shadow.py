"""
Shadow mode must behave like live: Octos's "would say" notes count as
what it said (so earlier questions aren't answered again, and it doesn't
introduce itself twice), but only in shadow. After going live, notes the
customer never received must not count.
"""
from datetime import timedelta

from django.test import TestCase, override_settings

from apps.communications.assistant import brain, prompt
from apps.communications.models import Message
from apps.communications.tests import make_conversation
from apps.communications.tests_whatsapp_outbound import customer_wrote


class ShadowHistoryTests(TestCase):

    def setUp(self):
        self.conv = make_conversation(None, contact_phone='+233244999001')
        customer_wrote(self.conv, timedelta(minutes=3))
        note = Message.objects.create(
            conversation=self.conv, direction=Message.OUTBOUND, channel=Message.SYSTEM,
            message_type=Message.NOTE, is_internal_note=True,
            body="Octos would say: Octos here, Farhat's assistant. We're open till 7:30pm.\n"
                 'Octos would hand to a person: test',
        )
        Message.objects.filter(pk=note.pk).update(created_at=note.created_at - timedelta(minutes=2))
        customer_wrote(self.conv, timedelta(minutes=1))

    @override_settings(OCTOS_ASSISTANT_MODE='shadow')
    def test_in_shadow_a_note_counts_as_what_octos_said(self):
        turns = brain._history(self.conv)
        self.assertEqual([t['role'] for t in turns], ['user', 'assistant', 'user'])
        self.assertEqual(turns[1]['content'], "Octos here, Farhat's assistant. We're open till 7:30pm.")

    @override_settings(OCTOS_ASSISTANT_MODE='shadow')
    def test_in_shadow_octos_does_not_introduce_itself_twice(self):
        self.assertIn(prompt.INTRO_DONE, prompt.system_prompt(self.conv, [])[1]['text'])

    @override_settings(OCTOS_ASSISTANT_MODE='live')
    def test_once_live_notes_the_customer_never_saw_dont_count(self):
        turns = brain._history(self.conv)
        self.assertEqual([t['role'] for t in turns], ['user'])
        self.assertIn(prompt.INTRO_FIRST, prompt.system_prompt(self.conv, [])[1]['text'])