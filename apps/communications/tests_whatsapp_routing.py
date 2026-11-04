"""
System messages choosing their channel: WhatsApp inside the 24-hour
window, SMS otherwise, SMS again if WhatsApp fails, and a welcome that
is sent once across both channels.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase

from apps.communications.models import Conversation, Message
from apps.communications.services import whatsapp_client, whatsapp_outbound
from apps.communications.tests_whatsapp_outbound import PHONE, conversation, customer_wrote
from apps.storefront.services import welcome

LOCAL = '0244123456'  # the same number, typed the Ghanaian way


class TrySendTextTests(TestCase):

    def test_open_window_queues_whatsapp_with_its_kind(self):
        conv = conversation()
        customer_wrote(conv, timedelta(minutes=10))
        msg = whatsapp_outbound.try_send_text(LOCAL, 'Your banners are ready', kind='ready')
        self.assertIsNotNone(msg)
        self.assertEqual(msg.kind, 'ready')
        self.assertEqual(msg.status, Message.QUEUED)
        self.assertEqual(msg.conversation, conv)

    def test_closed_window_means_sms(self):
        conv = conversation()
        customer_wrote(conv, timedelta(hours=30))
        self.assertIsNone(whatsapp_outbound.try_send_text(PHONE, 'hi', kind='ready'))

    def test_no_conversation_means_sms(self):
        self.assertIsNone(whatsapp_outbound.try_send_text(PHONE, 'hi', kind='ready'))

    def test_spam_conversation_never_gets_whatsapp(self):
        conv = conversation(status=Conversation.SPAM)
        customer_wrote(conv, timedelta(minutes=10))
        self.assertIsNone(whatsapp_outbound.try_send_text(PHONE, 'hi', kind='ready'))

    def test_unreal_number_means_sms(self):
        self.assertIsNone(whatsapp_outbound.try_send_text('12345', 'hi', kind='ready'))


class FallbackTests(TestCase):

    def queued(self, kind):
        conv = conversation()
        return Message.objects.create(
            conversation=conv, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
            status=Message.QUEUED, body='Your banners are ready', kind=kind,
        )

    @patch('apps.storefront.services.sms.send_sms')
    @patch('apps.communications.services.whatsapp_client.send_text',
           side_effect=whatsapp_client.WhatsAppError('131026', 'Message undeliverable'))
    def test_failed_system_message_goes_by_sms(self, send_text, send_sms):
        msg = self.queued('ready')
        whatsapp_outbound.deliver(msg.pk)
        send_sms.assert_called_once_with(PHONE, 'Your banners are ready', kind='ready')

    @patch('apps.storefront.services.sms.send_sms')
    @patch('apps.communications.services.whatsapp_client.send_text',
           side_effect=whatsapp_client.WhatsAppError('131026', 'Message undeliverable'))
    def test_failed_reply_stays_failed_without_sms(self, send_text, send_sms):
        msg = self.queued('')
        whatsapp_outbound.deliver(msg.pk)
        send_sms.assert_not_called()

    @patch('apps.storefront.services.sms.send_sms')
    @patch('apps.communications.services.whatsapp_client.send_text',
           side_effect=whatsapp_client.WhatsAppError('131026', 'Message undeliverable'))
    def test_fallback_sms_sent_once_even_if_deliver_runs_twice(self, send_text, send_sms):
        msg = self.queued('ready')
        whatsapp_outbound.deliver(msg.pk)
        whatsapp_outbound.deliver(msg.pk)
        send_sms.assert_called_once()

    @patch('apps.storefront.services.sms.send_sms')
    @patch('apps.communications.services.whatsapp_client.send_text', return_value='wamid.OK')
    def test_success_sends_no_sms(self, send_text, send_sms):
        msg = self.queued('ready')
        whatsapp_outbound.deliver(msg.pk)
        send_sms.assert_not_called()


class WelcomeAcrossChannelsTests(TestCase):

    @patch('apps.storefront.services.sms.send_sms')
    def test_open_window_welcomes_on_whatsapp_not_sms(self, send_sms):
        conv = conversation()
        customer_wrote(conv, timedelta(minutes=10))
        self.assertTrue(welcome.greet(LOCAL, 'Ama'))
        send_sms.assert_not_called()
        msg = conv.messages.get(direction=Message.OUTBOUND)
        self.assertEqual(msg.kind, welcome.KIND)
        self.assertIn('Ama', msg.body)

    @patch('apps.storefront.services.sms.send_sms', return_value=True)
    def test_closed_window_welcomes_by_sms(self, send_sms):
        conv = conversation()
        customer_wrote(conv, timedelta(hours=30))
        self.assertTrue(welcome.greet(LOCAL, 'Ama'))
        send_sms.assert_called_once()

    @patch('apps.storefront.services.sms.send_sms')
    def test_whatsapp_welcome_counts_so_no_second_welcome(self, send_sms):
        conv = conversation()
        customer_wrote(conv, timedelta(minutes=10))
        welcome.greet(LOCAL, 'Ama')
        self.assertTrue(welcome.already_welcomed(LOCAL))
        self.assertFalse(welcome.greet(LOCAL, 'Ama'))
        self.assertEqual(conv.messages.filter(kind=welcome.KIND).count(), 1)
        send_sms.assert_not_called()

    def test_failed_whatsapp_welcome_does_not_count(self):
        conv = conversation()
        Message.objects.create(
            conversation=conv, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
            status=Message.FAILED, body='Welcome', kind=welcome.KIND,
        )
        self.assertFalse(welcome.already_welcomed(LOCAL))