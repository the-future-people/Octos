"""
Receipts for customers who write from a WhatsApp username (14 Nov 2026).

They have no number, so no customer record, and the cashier's "Send receipt"
said "no phone number". The job is still linked to their chat, and the chat
reaches them by their WhatsApp user id: the receipt goes there.

Run: docker compose exec web python manage.py test apps.communications.tests_username_receipts -t .
"""
from decimal import Decimal

from django.test import TestCase

from apps.communications.models import Conversation, Message
from apps.communications.services.chat_customer import chat_for
from apps.communications.services.whatsapp_outbound import try_send_to
from apps.communications.tests import make_conversation, make_org
from apps.jobs.models import Job


class UsernameReceiptTests(TestCase):

    def setUp(self):
        self.branch = make_org()
        self.chat = make_conversation(None, contact_phone='')
        Conversation.objects.filter(pk=self.chat.pk).update(contact_user_id='GH.4417', contact_username='ama_prints')
        self.chat.refresh_from_db()
        self.job = Job.objects.create(
            branch=self.branch, job_type=Job.INSTANT, title='Photocopy', status=Job.PAID,
            payment_state=Job.Payment.SETTLED, estimated_cost=Decimal('5.00'), amount_paid=Decimal('5.00'),
        )
        self.chat.jobs.add(self.job)

    def wrote(self):
        Message.objects.create(conversation=self.chat, direction=Message.INBOUND,
                               channel=Message.WHATSAPP, body='Thanks')

    def test_the_job_finds_its_chat(self):
        self.assertEqual(chat_for(self.job), self.chat)

    def test_a_chat_with_no_number_gets_the_receipt_while_its_window_is_open(self):
        self.wrote()
        message = try_send_to(self.chat, "Here's your receipt.", kind='receipt')
        self.assertIsNotNone(message)
        self.assertEqual(message.status, Message.QUEUED)
        self.assertEqual(message.kind, 'receipt')

    def test_no_window_no_receipt(self):
        self.assertIsNone(try_send_to(self.chat, "Here's your receipt.", kind='receipt'))

    def test_a_spam_chat_gets_nothing(self):
        self.wrote()
        Conversation.objects.filter(pk=self.chat.pk).update(status=Conversation.SPAM)
        self.chat.refresh_from_db()
        self.assertIsNone(try_send_to(self.chat, "Here's your receipt.", kind='receipt'))
