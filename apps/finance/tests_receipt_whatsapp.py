"""
Sending a receipt on WhatsApp: only inside the customer's 24-hour window,
an honest reason when not, and never a receipt marked sent that wasn't.

Receipts are built with the stranded-sheet fixtures (RecoveryFixtureMixin),
which make them without a job. Where a test needs the text itself, the
formatter is patched; the one test that leaves it alone proves a receipt
that can't be written out says so, rather than blaming WhatsApp.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase

from apps.communications.models import Message
from apps.communications.tests import make_conversation
from apps.communications.tests_whatsapp_outbound import customer_wrote
from apps.finance.models import Receipt
from apps.finance.receipt_engine import ReceiptEngine
from apps.finance.tests import RecoveryFixtureMixin

FORMAT = 'apps.finance.receipt_engine.ReceiptEngine._format_whatsapp_message'


class ReceiptWhatsAppTests(RecoveryFixtureMixin, TestCase):

    def setUp(self):
        self.receipt = self.add_cash_receipt(self.make_sheet(days_ago=0), 58.50)
        Receipt.objects.filter(pk=self.receipt.pk).update(customer_phone='0244123456')
        self.receipt.refresh_from_db()
        self.engine = ReceiptEngine(self.branch)

    def open_window(self):
        conv = make_conversation(None, contact_phone='+233244123456')
        customer_wrote(conv, timedelta(minutes=10))
        return conv

    def assert_untouched(self):
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.whatsapp_status, Receipt.DeliveryStatus.PENDING)
        self.assertFalse(Message.objects.filter(direction=Message.OUTBOUND).exists())

    def test_no_phone_says_so(self):
        Receipt.objects.filter(pk=self.receipt.pk).update(customer_phone='')
        self.receipt.refresh_from_db()
        sent, reason = self.engine.send_whatsapp(self.receipt)
        self.assertFalse(sent)
        self.assertIn('no phone', reason)
        self.assert_untouched()

    def test_closed_window_gives_the_reason_and_leaves_the_receipt(self):
        with patch(FORMAT, return_value='Receipt text'):
            sent, reason = self.engine.send_whatsapp(self.receipt)
        self.assertFalse(sent)
        self.assertIn('24 hours', reason)
        self.assert_untouched()

    def test_open_window_queues_the_receipt_and_marks_it_sent(self):
        conv = self.open_window()
        with patch(FORMAT, return_value='Receipt text'):
            sent, reason = self.engine.send_whatsapp(self.receipt)
        self.assertTrue(sent)
        self.assertEqual(reason, '')
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.whatsapp_status, Receipt.DeliveryStatus.SENT)
        self.assertIsNotNone(self.receipt.whatsapp_sent_at)
        msg = conv.messages.get(direction=Message.OUTBOUND)
        self.assertEqual((msg.kind, msg.body), ('receipt', 'Receipt text'))

    def test_a_receipt_that_cannot_be_written_out_says_so(self):
        self.open_window()
        sent, reason = self.engine.send_whatsapp(self.receipt)  # no job: the formatter raises
        self.assertFalse(sent)
        self.assertIn("couldn't be prepared", reason)
        self.assert_untouched()