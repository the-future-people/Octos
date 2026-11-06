"""
Cards on WhatsApp: the client uploads then sends an image with its
caption; the sender stores the card on the message and delivers it as an
image; the payment notification sends the card, and falls back to text
when the card can't be drawn.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase, override_settings

from apps.communications.models import Message
from apps.communications.services import whatsapp_client, whatsapp_outbound
from apps.communications.tests import make_conversation
from apps.communications.tests_whatsapp_outbound import customer_wrote

MEMORY = {**settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}}
PNG = b'\x89PNG\r\n\x1a\nfake card'


@override_settings(STORAGES=MEMORY, WHATSAPP_ACCESS_TOKEN='t', WHATSAPP_PHONE_NUMBER_ID='123')
class CardTests(TestCase):

    def setUp(self):
        self.conv = make_conversation(None, contact_phone='+233244000333')
        customer_wrote(self.conv, timedelta(minutes=5))

    def test_the_client_uploads_then_sends_the_image_with_its_caption(self):
        uploaded = MagicMock(status_code=200); uploaded.json.return_value = {'id': 'MEDIA1'}
        sent = MagicMock(status_code=200); sent.json.return_value = {'messages': [{'id': 'wamid.CARD'}]}
        with patch('apps.communications.services.whatsapp_client.requests.post', side_effect=[uploaded, sent]) as post:
            wamid = whatsapp_client.send_image('+233244000333', PNG, 'paid.png', caption='Thanks James!')
        self.assertEqual(wamid, 'wamid.CARD')
        image = post.call_args_list[1].kwargs['json']['image']
        self.assertEqual(image, {'id': 'MEDIA1', 'caption': 'Thanks James!'})

    def test_a_card_is_stored_on_the_message_and_delivered_as_an_image(self):
        message = whatsapp_outbound.send_text(self.conv, 'Thanks James!', kind='paid', image=PNG, filename='paid.png')
        message.refresh_from_db()
        self.assertEqual((message.message_type, message.media_mime, message.body), (Message.IMAGE, 'image/png', 'Thanks James!'))
        with patch('apps.communications.services.whatsapp_client.send_image', return_value='wamid.CARD') as send:
            whatsapp_outbound.deliver(message.pk)
        self.assertEqual(send.call_args.args[1], PNG)
        self.assertEqual(send.call_args.kwargs['caption'], 'Thanks James!')
        message.refresh_from_db()
        self.assertEqual(message.status, Message.SENT)

    def test_text_messages_still_go_as_text(self):
        message = whatsapp_outbound.send_text(self.conv, 'Hello')
        with patch('apps.communications.services.whatsapp_client.send_text', return_value='wamid.T') as send:
            whatsapp_outbound.deliver(message.pk)
        send.assert_called_once()


class PaidNotificationTests(TestCase):

    def order(self):
        from apps.storefront.models import Lead, OnlineOrder
        lead = Lead.objects.create(phone='+233244000444', first_name='James')
        return OnlineOrder.objects.create(lead=lead, total=Decimal('50.00'), full_total=Decimal('50.00')), lead

    def test_paid_goes_as_the_card_with_its_caption(self):
        from apps.storefront.services.notify import _send_whatsapp
        order, lead = self.order()
        with patch('apps.communications.services.whatsapp_outbound.try_send_text') as send:
            _send_whatsapp(order, lead, 'paid', 'SMS text')
        self.assertTrue(send.call_args.kwargs['image'].startswith(b'\x89PNG'))
        self.assertIn('We got your payment (GHS 50.00)', send.call_args.args[1])
        self.assertIn(f'/t/{order.short_code}', send.call_args.args[1])

    def test_a_card_that_cant_be_drawn_falls_back_to_text(self):
        from apps.storefront.services.notify import _send_whatsapp
        order, lead = self.order()
        with patch('apps.storefront.services.cards.paid_card', side_effect=RuntimeError('no font')), \
                patch('apps.storefront.services.cards.CARDS', {'paid': lambda o: (_ for _ in ()).throw(RuntimeError('no font'))}), \
                patch('apps.communications.services.whatsapp_outbound.try_send_text') as send:
            _send_whatsapp(order, lead, 'paid', 'SMS text')
        self.assertNotIn('image', send.call_args.kwargs)