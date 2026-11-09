"""
The inbox, live (9 Nov 2026): a saved message is announced to the portals.
"""
from unittest.mock import patch

from django.test import TestCase

from apps.communications.models import Message
from apps.communications.tests import make_conversation, make_org


class LiveInboxTests(TestCase):

    def test_a_new_message_is_announced(self):
        make_org()
        conv = make_conversation(None, contact_phone='+233244000888')
        with patch('apps.core.broadcast.broadcast_invalidation') as told:
            with self.captureOnCommitCallbacks(execute=True):
                Message.objects.create(conversation=conv, direction=Message.INBOUND,
                                       channel=conv.channel, body='Hello')
        self.assertTrue(told.called)
        self.assertIn(f'conversation:{conv.pk}', told.call_args[0][1])
