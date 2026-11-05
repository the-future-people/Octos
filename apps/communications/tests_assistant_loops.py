"""
The loop guard tells a bot from a busy customer by speed, not volume.
The first test is the Albion Travel conversation of 5 Nov 2026: a normal
human order, six exchanges in ten minutes, wrongly handed over by the old
"4 replies in 10 minutes" rule, and handed over again the moment a person
handed it back.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.communications.assistant import brain
from apps.communications.models import Conversation, Message
from apps.communications.tests import make_conversation


class LoopGuardTests(TestCase):

    def setUp(self):
        self.now = timezone.now()
        self.conv = make_conversation(None, contact_phone='+233538890170')

    def say(self, who, seconds_ago, body='...'):
        msg = Message.objects.create(
            conversation=self.conv, channel=Message.WHATSAPP, body=body,
            direction=Message.INBOUND if who == 'customer' else Message.OUTBOUND,
        )
        Message.objects.filter(pk=msg.pk).update(created_at=self.now - timedelta(seconds=seconds_ago))

    def test_a_busy_human_conversation_is_not_a_bot(self):
        # Customer and Octos taking turns, a minute or so apart.
        for i, (who, body) in enumerate([
            ('customer', 'Hello'), ('octos', 'Hello! Octos here'),
            ('customer', 'Uhm okay'), ('customer', 'I want to print something'),
            ('octos', 'Sure! What would you like to print?'), ('customer', 'This file'),
            ('octos', 'How many pages?'), ('customer', "It's a sticker 3 x 3 inches"),
            ('octos', 'How many do you want?'), ('customer', 'I will want 157 pcs'),
            ('octos', 'Got it'), ('customer', 'Please I am waiting on your reply'),
        ]):
            self.say(who, 540 - i * 45, body)
        self.assertIsNone(brain._looks_automated(self.conv, self.now))

    def test_replies_within_seconds_of_octos_twice_is_a_bot(self):
        self.say('octos', 300, 'Hello! Octos here')
        self.say('customer', 298, 'Thank you for contacting us, we will respond shortly')
        self.say('octos', 200, 'How can I help?')
        self.say('customer', 197, 'Thank you for contacting us, we will respond shortly')
        self.assertIn('within seconds', brain._looks_automated(self.conv, self.now))

    def test_one_fast_reply_is_not_enough(self):
        self.say('octos', 300, 'Hello! Octos here')
        self.say('customer', 297, 'ok')
        self.say('octos', 200, 'How can I help?')
        self.say('customer', 120, 'Price for A3 please')
        self.assertIsNone(brain._looks_automated(self.conv, self.now))

    def test_a_hand_back_starts_the_count_afresh(self):
        self.say('octos', 300, 'Hello! Octos here')
        self.say('customer', 298, 'auto')
        self.say('octos', 200, 'How can I help?')
        self.say('customer', 197, 'auto')
        Conversation.objects.filter(pk=self.conv.pk).update(handled_since=self.now - timedelta(seconds=60))
        self.conv.refresh_from_db()
        self.say('customer', 30, 'Please I am waiting on your reply')
        self.assertIsNone(brain._looks_automated(self.conv, self.now))