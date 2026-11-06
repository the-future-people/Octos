"""
Waking Octos: a customer's message wakes it 8 seconds later (so a burst
gets one reply); handing a conversation back wakes it at once if the
customer is still waiting; when the assistant is off, nothing is queued.
"""
import json
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings

from apps.communications.models import Message
from apps.communications.services import handover
from apps.communications.tests import make_conversation
from apps.communications.tests_whatsapp import WebhookTestCase, delivery, text
from apps.communications.tests_whatsapp_outbound import customer_wrote

WAKE = 'apps.communications.tasks.answer_whatsapp.apply_async'


class WakeTests(WebhookTestCase):

    def deliver_now(self, payload):
        """A signed delivery, with its after-commit work run as the real request would."""
        with self.captureOnCommitCallbacks(execute=True):
            self.deliver(payload)

    @override_settings(OCTOS_ASSISTANT_MODE='shadow')
    def test_a_customer_message_wakes_octos_after_a_pause(self):
        with patch(WAKE) as wake:
            self.deliver_now(delivery(text('Good evening please are you open?')))
        msg = Message.objects.get(direction=Message.INBOUND)
        wake.assert_called_once_with((msg.conversation_id, msg.pk), countdown=8)

    @override_settings(OCTOS_ASSISTANT_MODE='off')
    def test_off_queues_nothing(self):
        with patch(WAKE) as wake:
            self.deliver_now(delivery(text('Hello')))
        wake.assert_not_called()

    @override_settings(OCTOS_ASSISTANT_MODE='live')
    def test_a_meta_retry_does_not_wake_octos_twice(self):
        with patch(WAKE) as wake:
            self.deliver_now(delivery(text('Hello')))
            self.deliver_now(delivery(text('Hello')))
        self.assertEqual(wake.call_count, 1)

    @override_settings(OCTOS_ASSISTANT_MODE='live')
    def test_handing_back_answers_a_customer_still_waiting(self):
        conv = make_conversation(None, contact_phone='+233244888001')
        waiting = customer_wrote(conv, timedelta(minutes=40))
        with patch(WAKE) as wake, self.captureOnCommitCallbacks(execute=True):
            handover.hand_back(conv, why='no reply 10 minutes after the reminder.')
        wake.assert_called_once_with((conv.pk, waiting.pk), countdown=0)

    @override_settings(OCTOS_ASSISTANT_MODE='live')
    def test_handing_back_with_nobody_waiting_wakes_nothing(self):
        conv = make_conversation(None, contact_phone='+233244888002')
        customer_wrote(conv, timedelta(minutes=40))
        Message.objects.create(conversation=conv, direction=Message.OUTBOUND,
                               channel=Message.WHATSAPP, body='Ready by 4pm 👍')
        with patch(WAKE) as wake, self.captureOnCommitCallbacks(execute=True):
            handover.hand_back(conv, why='test')
        wake.assert_not_called()


    @override_settings(OCTOS_ASSISTANT_MODE='live')
    def test_no_typing_dots_the_moment_a_message_arrives(self):
        # The dots now show only once Octos really starts writing.
        with patch(WAKE), patch('apps.communications.services.whatsapp_client.show_typing') as dots:
            self.deliver_now(delivery(text('Good evening please are you open?')))
        dots.assert_not_called()

    @override_settings(OCTOS_ASSISTANT_MODE='shadow')
    def test_shadow_never_shows_typing(self):
        with patch(WAKE), patch('apps.communications.tasks.show_whatsapp_typing.delay') as typing:
            self.deliver_now(delivery(text('Hello')))
        typing.assert_not_called()