"""
The spine is told what happens in conversations (Layer 1, Step 1.1b, 10 Nov 2026):
messages received, delivery receipts, take-overs, hand-backs, resolutions.
Each fact is recorded once, even when WhatsApp delivers it twice.
"""
from django.test import TestCase, override_settings

from apps.communications.models import Conversation, Message
from apps.communications.services import handover
from apps.communications.services.whatsapp_inbound import _apply_status, _receive
from apps.spine import kinds
from apps.spine.models import Event


def _text(wamid, body='Hi'):
    return {'id': wamid, 'from': '233244123456', 'type': 'text', 'text': {'body': body}}


@override_settings(OCTOS_ASSISTANT_MODE='off')
class InboundEventsTests(TestCase):
    def test_a_received_message_is_recorded_on_the_spine(self):
        self.assertTrue(_receive(_text('wamid.T1'), 'Ama'))
        event = Event.objects.get()
        self.assertEqual(event.kind, kinds.MESSAGE_RECEIVED)
        self.assertEqual(event.actor, Event.CUSTOMER)
        self.assertEqual(event.idempotency_key, 'wa:wamid.T1')
        self.assertEqual(event.conversation, Message.objects.get().conversation)

    def test_a_redelivered_message_is_recorded_once(self):
        _receive(_text('wamid.T2'), 'Ama')
        self.assertFalse(_receive(_text('wamid.T2'), 'Ama'))   # Meta retried
        self.assertEqual(Event.objects.filter(kind=kinds.MESSAGE_RECEIVED).count(), 1)

    def test_a_delivery_receipt_is_recorded_once(self):
        _receive(_text('wamid.T3'), 'Ama')
        conversation = Conversation.objects.get()
        Message.objects.create(conversation=conversation, direction=Message.OUTBOUND,
                               channel=Message.WHATSAPP, message_type=Message.TEXT,
                               body='Hello', external_id='wamid.OUT1', status=Message.SENT)
        _apply_status({'id': 'wamid.OUT1', 'status': 'delivered'})
        _apply_status({'id': 'wamid.OUT1', 'status': 'delivered'})   # Meta retried
        self.assertEqual(Event.objects.filter(kind=kinds.MESSAGE_DELIVERED).count(), 1)

    def test_a_failed_send_records_metas_reason(self):
        _receive(_text('wamid.T4'), 'Ama')
        conversation = Conversation.objects.get()
        Message.objects.create(conversation=conversation, direction=Message.OUTBOUND,
                               channel=Message.WHATSAPP, message_type=Message.TEXT,
                               body='Hello', external_id='wamid.OUT2', status=Message.SENT)
        _apply_status({'id': 'wamid.OUT2', 'status': 'failed',
                       'errors': [{'code': 131026, 'title': 'Message undeliverable'}]})
        event = Event.objects.get(kind=kinds.MESSAGE_FAILED)
        self.assertIn('131026', event.reason)


@override_settings(OCTOS_ASSISTANT_MODE='off')
class HandoverEventsTests(TestCase):
    def setUp(self):
        self.conversation = Conversation.objects.create(
            branch=None, contact_phone='+233244123456', channel=Conversation.WHATSAPP)

    def test_octos_taking_back_is_recorded_with_its_reason(self):
        handover.hand_back(self.conversation, why='no reply 10 minutes after the reminder.')
        event = Event.objects.get()
        self.assertEqual(event.kind, kinds.OCTOS_TOOK_BACK)
        self.assertEqual(event.actor, Event.OCTOS)
        self.assertIn('no reply 10 minutes', event.reason)

    def test_octos_asking_for_a_person_is_recorded(self):
        handover.octos_hands_over(self.conversation, 'customer asked to be called')
        event = Event.objects.get()
        self.assertEqual(event.kind, kinds.OCTOS_ASKED_FOR_PERSON)
        self.assertIn('customer asked to be called', event.reason)

    def test_resolving_is_recorded(self):
        handover.resolved(self.conversation)
        self.assertEqual(Event.objects.get().kind, kinds.CONVERSATION_RESOLVED)
