"""
The sender: the HTTP client, the 24-hour window, send_text and deliver,
and delivery statuses moving outbound messages forward. Meta is never
called; requests and the client are patched.
"""
import uuid
from datetime import timedelta
from unittest.mock import Mock, patch

import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.communications.models import Conversation, Message, WhatsAppEvent
from apps.communications.services import whatsapp_client, whatsapp_outbound
from apps.communications.services.window import window_open
from apps.communications.tests import make_conversation
from apps.communications.tests_whatsapp import AMA, PHONE_ID, WebhookTestCase, delivery

PHONE = '+233244123456'


def conversation(**kwargs):
    return make_conversation(None, contact_phone=PHONE, **kwargs)


def customer_wrote(conv, ago):
    """An inbound WhatsApp message, backdated: created_at can't be set on create."""
    msg = Message.objects.create(conversation=conv, direction=Message.INBOUND,
                                 channel=Message.WHATSAPP, body='hi',
                                 external_id=f'wamid.in.{uuid.uuid4().hex[:12]}')
    Message.objects.filter(pk=msg.pk).update(created_at=timezone.now() - ago)
    return msg


def outbound(conv, status=Message.SENT, wamid='wamid.OUT1'):
    return Message.objects.create(conversation=conv, direction=Message.OUTBOUND,
                                  channel=Message.WHATSAPP, body='Your banners are ready',
                                  status=status, external_id=wamid)


def meta_answers(data, status_code=200):
    response = Mock(status_code=status_code)
    response.json.return_value = data
    return response


@override_settings(WHATSAPP_ACCESS_TOKEN='test-token', WHATSAPP_PHONE_NUMBER_ID=PHONE_ID)
class ClientTests(TestCase):

    @patch('apps.communications.services.whatsapp_client.requests.post')
    def test_text_sent_in_metas_shape_and_wamid_returned(self, post):
        post.return_value = meta_answers({'messages': [{'id': 'wamid.OUT1'}]})
        self.assertEqual(whatsapp_client.send_text('0244123456', 'hello'), 'wamid.OUT1')
        url = post.call_args.args[0]
        payload = post.call_args.kwargs['json']
        self.assertIn(f'/{whatsapp_client.API_VERSION}/{PHONE_ID}/messages', url)
        self.assertEqual(payload['to'], '233244123456')  # digits, no '+'
        self.assertEqual(payload['text']['body'], 'hello')

    @patch('apps.communications.services.whatsapp_client.requests.post')
    def test_meta_error_raised_with_its_code(self, post):
        post.return_value = meta_answers(
            {'error': {'code': 131047, 'message': 'Re-engagement message'}}, 400)
        with self.assertRaises(whatsapp_client.WhatsAppError) as caught:
            whatsapp_client.send_text(PHONE, 'hello')
        self.assertEqual(caught.exception.code, '131047')

    @patch('apps.communications.services.whatsapp_client.requests.post',
           side_effect=requests.ConnectionError('down'))
    def test_network_failure_raised_as_network(self, post):
        with self.assertRaises(whatsapp_client.WhatsAppError) as caught:
            whatsapp_client.send_text(PHONE, 'hello')
        self.assertEqual(caught.exception.code, 'network')

    @patch('apps.communications.services.whatsapp_client.requests.post')
    def test_unreal_number_refused_before_meta_is_asked(self, post):
        with self.assertRaises(whatsapp_client.WhatsAppError) as caught:
            whatsapp_client.send_text('12345', 'hello')
        self.assertEqual(caught.exception.code, 'invalid_number')
        post.assert_not_called()

    @override_settings(WHATSAPP_ACCESS_TOKEN='')
    def test_missing_token_is_loud(self):
        with self.assertRaises(ImproperlyConfigured):
            whatsapp_client.send_text(PHONE, 'hello')


class WindowTests(TestCase):

    def test_never_written_is_closed(self):
        self.assertFalse(window_open(conversation()))

    def test_open_an_hour_after_the_customer_wrote(self):
        conv = conversation()
        customer_wrote(conv, timedelta(hours=1))
        self.assertTrue(window_open(conv))

    def test_closed_in_the_safety_margin(self):
        conv = conversation()
        customer_wrote(conv, timedelta(hours=23, minutes=56))
        self.assertFalse(window_open(conv))

    def test_our_own_messages_do_not_open_it(self):
        conv = conversation()
        outbound(conv)
        self.assertFalse(window_open(conv))


class SendTextTests(TestCase):

    def test_open_window_queues_and_hands_to_worker_after_commit(self):
        conv = conversation()
        customer_wrote(conv, timedelta(minutes=10))
        with patch('apps.communications.tasks.deliver_whatsapp.delay') as delay:
            with self.captureOnCommitCallbacks(execute=True):
                msg = whatsapp_outbound.send_text(conv, 'See you at 4 👍')
        self.assertEqual(msg.status, Message.QUEUED)
        self.assertEqual(msg.direction, Message.OUTBOUND)
        self.assertIsNone(msg.sent_by)  # Octos
        delay.assert_called_once_with(msg.pk)

    def test_closed_window_refused_and_nothing_recorded(self):
        conv = conversation()
        customer_wrote(conv, timedelta(hours=30))
        with self.assertRaises(whatsapp_outbound.WindowClosed):
            whatsapp_outbound.send_text(conv, 'hello')
        self.assertFalse(conv.messages.filter(direction=Message.OUTBOUND).exists())

    def test_not_a_whatsapp_conversation_refused(self):
        conv = make_conversation(None, channel=Conversation.EMAIL, contact_phone=PHONE)
        with self.assertRaises(ValueError):
            whatsapp_outbound.send_text(conv, 'hello')

    def test_empty_text_refused(self):
        conv = conversation()
        customer_wrote(conv, timedelta(minutes=10))
        with self.assertRaises(ValueError):
            whatsapp_outbound.send_text(conv, '   ')


class DeliverTests(TestCase):

    def setUp(self):
        self.msg = outbound(conversation(), status=Message.QUEUED, wamid='')

    @patch('apps.communications.services.whatsapp_client.send_text', return_value='wamid.OUT9')
    def test_sent_records_the_wamid(self, send):
        whatsapp_outbound.deliver(self.msg.pk)
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.status, Message.SENT)
        self.assertEqual(self.msg.external_id, 'wamid.OUT9')
        send.assert_called_once_with(PHONE, 'Your banners are ready')

    @patch('apps.communications.services.whatsapp_client.send_text',
           side_effect=whatsapp_client.WhatsAppError('131026', 'Message undeliverable'))
    def test_meta_refusal_recorded_with_its_reason(self, send):
        whatsapp_outbound.deliver(self.msg.pk)
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.status, Message.FAILED)
        self.assertIn('131026', self.msg.error)

    @patch('apps.communications.services.whatsapp_client.send_text',
           side_effect=RuntimeError('boom'))
    def test_unexpected_error_still_ends_failed(self, send):
        whatsapp_outbound.deliver(self.msg.pk)
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.status, Message.FAILED)
        self.assertIn('internal', self.msg.error)

    @patch('apps.communications.services.whatsapp_client.send_text', return_value='wamid.OUT9')
    def test_running_twice_sends_once(self, send):
        whatsapp_outbound.deliver(self.msg.pk)
        whatsapp_outbound.deliver(self.msg.pk)
        send.assert_called_once()


class StatusTests(WebhookTestCase):

    def setUp(self):
        self.msg = outbound(conversation())

    def receipt(self, word, wamid='wamid.OUT1', errors=None):
        status = {'id': wamid, 'status': word, 'timestamp': '1762270000', 'recipient_id': AMA}
        if errors:
            status['errors'] = errors
        self.deliver(delivery(statuses=[status]))
        self.msg.refresh_from_db()

    def test_delivered_then_read(self):
        self.receipt('delivered')
        self.assertEqual(self.msg.status, Message.DELIVERED)
        self.receipt('read')
        self.assertEqual(self.msg.status, Message.READ)

    def test_late_delivered_does_not_undo_read(self):
        self.receipt('read')
        self.receipt('delivered')
        self.assertEqual(self.msg.status, Message.READ)

    def test_failed_records_metas_reason(self):
        self.receipt('failed', errors=[{'code': 131026, 'title': 'Message undeliverable'}])
        self.assertEqual(self.msg.status, Message.FAILED)
        self.assertIn('131026', self.msg.error)

    def test_receipt_for_unknown_message_changes_nothing(self):
        self.receipt('read', wamid='wamid.SOMEONE_ELSE')
        self.assertEqual(self.msg.status, Message.SENT)
        self.assertEqual(WhatsAppEvent.objects.get().error, '')