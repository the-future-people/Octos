"""
The WhatsApp receipt goes in the background (17 Nov 2026): the quick checks
answer at once, the drawing and sending happen in the worker, so it is sent
even when the cashier closes the receipt or moves on.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase

from apps.communications.models import Message
from apps.communications.tests import make_conversation
from apps.communications.tests_whatsapp_outbound import customer_wrote
from apps.finance.models import Receipt
from apps.finance.receipt_engine import NOT_WRITTEN, ReceiptEngine
from apps.finance.tasks import send_receipt_whatsapp
from apps.finance.tests import RecoveryFixtureMixin

FORMAT = 'apps.finance.receipt_engine.ReceiptEngine._format_whatsapp_message'
DELAY = 'apps.finance.tasks.send_receipt_whatsapp.delay'


class BackgroundReceiptTests(RecoveryFixtureMixin, TestCase):

    def setUp(self):
        self.receipt = self.add_cash_receipt(self.make_sheet(days_ago=0), 58.50)
        Receipt.objects.filter(pk=self.receipt.pk).update(customer_phone='0244123456')
        self.receipt.refresh_from_db()
        self.engine = ReceiptEngine(self.branch)

    def open_window(self):
        conv = make_conversation(None, contact_phone='+233244123456')
        customer_wrote(conv, timedelta(minutes=10))
        return conv

    def test_queued_after_the_request_not_sent_in_it(self):
        self.open_window()
        with patch(DELAY) as later, self.captureOnCommitCallbacks(execute=True):
            queued, reason = self.engine.queue_whatsapp(self.receipt)
        self.assertEqual((queued, reason), (True, ''))
        later.assert_called_once_with(self.receipt.pk)
        self.assertFalse(Message.objects.filter(direction=Message.OUTBOUND).exists())

    def test_a_closed_window_is_said_at_once_and_nothing_queued(self):
        with patch(DELAY) as later, self.captureOnCommitCallbacks(execute=True):
            queued, reason = self.engine.queue_whatsapp(self.receipt)
        self.assertEqual((queued, reason), (False, NOT_WRITTEN))
        later.assert_not_called()

    def test_the_worker_sends_it(self):
        conv = self.open_window()
        with patch(FORMAT, return_value='Receipt text'):
            send_receipt_whatsapp(self.receipt.pk)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.whatsapp_status, Receipt.DeliveryStatus.SENT)
        self.assertTrue(conv.messages.filter(direction=Message.OUTBOUND, kind='receipt').exists())

    def test_the_worker_marks_a_failure_on_the_receipt(self):
        with patch(FORMAT, return_value='Receipt text'):
            send_receipt_whatsapp(self.receipt.pk)       # the window shut before it ran
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.whatsapp_status, Receipt.DeliveryStatus.FAILED)

    def test_a_payment_asked_to_send_it_queues_it_and_says_so(self):
        from apps.jobs.api.views import _queue_whatsapp_receipt
        self.open_window()
        result = {'receipt_id': self.receipt.pk}
        with patch(DELAY) as later, self.captureOnCommitCallbacks(execute=True):
            _queue_whatsapp_receipt(result, {'send_whatsapp': True})
        self.assertEqual(result['whatsapp'], {'queued': True, 'detail': 'Sending on WhatsApp.'})
        later.assert_called_once_with(self.receipt.pk)

    def test_a_payment_not_asked_leaves_it(self):
        from apps.jobs.api.views import _queue_whatsapp_receipt
        result = {'receipt_id': self.receipt.pk}
        _queue_whatsapp_receipt(result, {'send_whatsapp': False})
        self.assertNotIn('whatsapp', result)
