"""
The inbox, light (9 Nov 2026): only what's new, and reading never announces.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.communications.models import Message
from apps.communications.tests import make_conversation, make_org


class LightChatTests(TestCase):

    def setUp(self):
        make_org()
        self.conv = make_conversation(None, contact_phone='+233244000555')
        self.ids = [Message.objects.create(conversation=self.conv, direction=Message.INBOUND,
                                           channel=self.conv.channel, body=f'm{i}').pk for i in range(30)]
        self.api = APIClient()
        self.api.force_authenticate(get_user_model().objects.create_user(
            email='light@farhat.test', password='x', first_name='Esi', last_name='Ofori'))

    def test_after_sends_only_new_and_the_last_15(self):
        url = f'/api/v1/communications/{self.conv.pk}/'
        everything = self.api.get(url).json()['messages']
        recent = self.api.get(url, {'after': self.ids[-1]}).json()['messages']
        self.assertEqual(len(everything), 30)
        self.assertEqual([m['id'] for m in recent], self.ids[-15:])

    def test_reading_a_chat_is_never_announced(self):
        with patch('apps.core.broadcast.broadcast_invalidation') as told:
            with self.captureOnCommitCallbacks(execute=True):
                self.api.get(f'/api/v1/communications/{self.conv.pk}/')
        self.assertFalse(told.called)
