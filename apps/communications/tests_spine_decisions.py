"""
Octos's decisions and every send reach the spine (Layer 1, Step 1.1c, 10 Nov 2026).
"""
import time
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.communications.assistant import brain
from apps.communications.models import AssistantRun, Conversation, Message
from apps.communications.services import whatsapp_client, whatsapp_outbound
from apps.spine import kinds
from apps.spine.models import Event


@override_settings(OCTOS_ASSISTANT_MODE='off')
class DecisionEventsTests(TestCase):
    def setUp(self):
        self.conversation = Conversation.objects.create(
            branch=None, contact_phone='+233244123456', channel=Conversation.WHATSAPP)
        self.trigger = Message.objects.create(
            conversation=self.conversation, direction=Message.INBOUND, channel=Message.WHATSAPP,
            message_type=Message.TEXT, body='Hi', external_id='wamid.IN1')

    def _run(self):
        return AssistantRun(conversation=self.conversation, trigger=self.trigger, mode='live')

    def test_staying_silent_is_recorded_with_octoss_reason(self):
        brain._finish(self._run(), AssistantRun.SKIPPED, time.monotonic(), reason='a person has it')
        event = Event.objects.get()
        self.assertEqual(event.kind, kinds.OCTOS_STAYED_SILENT)
        self.assertEqual(event.actor, Event.OCTOS)
        self.assertEqual(event.reason, 'a person has it')

    def test_replying_is_recorded(self):
        brain._finish(self._run(), AssistantRun.REPLIED, time.monotonic(), reply='Hello')
        self.assertEqual(Event.objects.get().kind, kinds.OCTOS_REPLIED)

    def test_a_run_finished_twice_is_recorded_once(self):
        run = self._run()
        brain._finish(run, AssistantRun.REPLIED, time.monotonic())
        brain._finish(run, AssistantRun.REPLIED, time.monotonic())
        self.assertEqual(Event.objects.count(), 1)


class SendEventsTests(TestCase):
    def setUp(self):
        self.conversation = Conversation.objects.create(
            branch=None, contact_phone='+233244123456', channel=Conversation.WHATSAPP)

    def _queued(self, kind=''):
        return Message.objects.create(
            conversation=self.conversation, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
            message_type=Message.TEXT, body='Hello', status=Message.QUEUED, kind=kind)

    @patch('apps.communications.services.whatsapp_client.send_text', return_value='wamid.SENT1')
    def test_octos_sending_is_recorded_as_octos(self, _send):
        message = self._queued()
        whatsapp_outbound.deliver(message.pk)
        event = Event.objects.get()
        self.assertEqual(event.kind, kinds.MESSAGE_SENT)
        self.assertEqual(event.actor, Event.OCTOS)
        self.assertEqual(event.payload['wamid'], 'wamid.SENT1')

    @patch('apps.communications.services.whatsapp_client.send_text', return_value='wamid.SENT2')
    def test_a_system_message_is_recorded_as_system(self, _send):
        message = self._queued(kind='ready')
        whatsapp_outbound.deliver(message.pk)
        self.assertEqual(Event.objects.get().actor, Event.SYSTEM)

    @patch('apps.communications.services.whatsapp_client.send_text', return_value='wamid.SENT3')
    def test_delivering_twice_records_once(self, _send):
        message = self._queued()
        whatsapp_outbound.deliver(message.pk)
        whatsapp_outbound.deliver(message.pk)
        self.assertEqual(Event.objects.filter(kind=kinds.MESSAGE_SENT).count(), 1)

    @patch('apps.communications.services.whatsapp_client.send_text',
           side_effect=whatsapp_client.WhatsAppError('network', 'down'))
    def test_a_failed_send_is_recorded_with_its_reason(self, _send):
        message = self._queued()
        whatsapp_outbound.deliver(message.pk)
        event = Event.objects.get()
        self.assertEqual(event.kind, kinds.MESSAGE_FAILED)
        self.assertIn('network', event.reason)
