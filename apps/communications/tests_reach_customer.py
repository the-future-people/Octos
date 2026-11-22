"""
Reaching a customer who never wrote, from the owner's line (22 Nov 2026).

Khofi asked Octos to thank Mr Kwaku Apau Hemeng for a GHS 1,967.48 order.
He had never written to us, and Octos said it had no way to message him.
WhatsApp allows an approved message first to anyone with a number: Octos
now shows the one that fits, word for word, and sends it on his yes.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.communications.assistant import boss, boss_tools
from apps.communications.models import Conversation, Message
from apps.communications.tests import make_org
from apps.communications.tests_whatsapp_outbound import customer_wrote
from apps.customers.models import CustomerProfile
from apps.jobs.models import Job

SEND = 'apps.communications.services.whatsapp_client._send'


class ReachCustomerTests(TestCase):

    def setUp(self):
        self.branch = make_org('-RCH')
        self.hemeng = CustomerProfile.objects.create(first_name='Kwaku', last_name='Apau Hemeng',
                                                     phone='0244771234', customer_type='INDIVIDUAL')
        self.job = Job.objects.create(branch=self.branch, status='COMPLETE', customer=self.hemeng, title='Bulk print',
                                      estimated_cost=Decimal('1967.48'))

    def test_a_customer_who_never_wrote_can_still_be_thanked(self):
        found = boss_tools.reach_customer('Kwaku Apau')
        self.assertFalse(found['can_write_freely'])
        self.assertIn('never written', found['why'])
        self.assertEqual(found['approved_messages']['thank_you_order'],
                         f'Hello Kwaku, thank you for your order {self.job.job_number} with Farhat Printing Press. '
                         'We truly appreciate your business, and it was a pleasure working on it for you 🙏')

    def test_sent_on_his_word_as_the_approved_message(self):
        with patch(SEND, return_value='wamid.t1') as send:
            done = boss_tools.send_approved('Hemeng', 'thank_you_order')
        self.assertTrue(done['sent'], done)
        payload = send.call_args.args[1]
        self.assertEqual(send.call_args.args[0], '+233244771234')
        self.assertEqual(payload['template']['name'], 'thank_you_order')
        self.assertEqual([p['text'] for p in payload['template']['components'][0]['parameters']],
                         ['Kwaku', self.job.job_number])
        chat = Conversation.objects.get(contact_phone='+233244771234')
        message = chat.messages.get(kind='template')
        self.assertEqual(message.status, Message.SENT)
        self.assertIn('thank you for your order', message.body)

    def test_inside_the_window_he_writes_freely_instead(self):
        chat = Conversation.objects.create(channel=Conversation.WHATSAPP, contact_phone='+233244771234',
                                           customer=self.hemeng)
        customer_wrote(chat, timedelta(minutes=5))
        self.assertTrue(boss_tools.reach_customer('Hemeng')['can_write_freely'])
        with patch(SEND) as send:
            self.assertFalse(boss_tools.send_approved('Hemeng', 'thank_you_order')['sent'])
        send.assert_not_called()

    def test_the_we_miss_you_note_respects_a_no(self):
        Conversation.objects.create(channel=Conversation.WHATSAPP, contact_phone='+233244771234',
                                    customer=self.hemeng, marketing_opt_out=True)
        with patch(SEND) as send:
            done = boss_tools.send_approved('Hemeng', 'reconnect')
        self.assertIn('asked not to', done['why'])
        send.assert_not_called()

    def test_only_our_approved_messages(self):
        self.assertIn('error', boss_tools.send_approved('Hemeng', 'receipt_ready'))

    def test_the_rules(self):
        self.assertIn('never tell him you have no way to message them', boss.RULES)
        self.assertIn('send it with send_approved only when he says yes', boss.RULES)

    def test_the_inbox_still_offers_them(self):
        from apps.communications.api.views import START_TEMPLATES
        self.assertIn('thank_you_order', START_TEMPLATES)


class ApprovalTests(ReachCustomerTests):
    """Octos offered the thank-you while Meta was still reviewing it (22 Nov 2026)."""

    def setUp(self):
        super().setUp()
        p = patch('apps.communications.services.templates.statuses',
                  return_value={'thank_you_order': 'PENDING', 'general_followup': 'APPROVED',
                                'order_ready': 'APPROVED', 'job_question': 'APPROVED', 'reconnect': 'APPROVED'})
        p.start()
        self.addCleanup(p.stop)

    def test_a_message_still_with_meta_is_not_offered(self):
        found = boss_tools.reach_customer('Hemeng')
        self.assertNotIn('thank_you_order', found['approved_messages'])
        self.assertIn('general_followup', found['approved_messages'])
        self.assertEqual(found['still_with_meta_for_approval'], ['thank_you_order'])

    def test_and_is_not_sent(self):
        with patch(SEND) as send:
            done = boss_tools.send_approved('Hemeng', 'thank_you_order')
        self.assertIn('still reviewing', done['why'])
        send.assert_not_called()

    # The inherited tests run with thank_you_order pending: the ones that send it don't apply here.
    test_a_customer_who_never_wrote_can_still_be_thanked = None
    test_sent_on_his_word_as_the_approved_message = None


from apps.finance.tests import RecoveryFixtureMixin  # noqa: E402


class SendReceiptTests(RecoveryFixtureMixin, TestCase):
    """'Can you send him his receipt then for that job?' (22 Nov 2026)."""

    def setUp(self):
        from apps.finance.models import Receipt
        self.hemeng = CustomerProfile.objects.create(first_name='Kwaku', last_name='Apau Hemeng',
                                                     phone='0244771234', customer_type='INDIVIDUAL')
        self.job = Job.objects.create(branch=self.branch, status='COMPLETE', customer=self.hemeng, title='Bulk',
                                      estimated_cost=Decimal('1967.48'))
        self.receipt = self.add_cash_receipt(self.make_sheet(days_ago=0), 1967.48)
        Receipt.objects.filter(pk=self.receipt.pk).update(job=self.job, customer_phone='')
        self.receipt.refresh_from_db()
        for p in (patch('apps.finance.services.receipt_image.render', return_value=b'\x89PNG fake'),
                  patch('apps.finance.services.receipt_image.receipt_data', return_value={'first_name': 'Kwaku'}),
                  patch('apps.finance.receipt_engine.ReceiptEngine._format_whatsapp_message', return_value='text'),
                  patch('apps.communications.services.whatsapp_client.upload_media', return_value='m1')):
            p.start()
            self.addCleanup(p.stop)

    def test_octos_shows_what_would_go(self):
        found = boss_tools.find_receipt(self.job.job_number)
        self.assertEqual(found['receipt'], self.receipt.receipt_number)
        self.assertIn('here is your receipt from Farhat Printing Press for GHS 1,967.48', found['would_send'])
        self.assertEqual(boss_tools.find_receipt('Hemeng')['receipt'], self.receipt.receipt_number)

    def test_sent_with_the_number_on_his_record_as_the_approved_receipt(self):
        with patch(SEND, return_value='wamid.r9') as send:
            done = boss_tools.send_receipt(self.job.job_number)
        self.assertTrue(done['sent'], done)
        self.assertEqual(send.call_args.args[0], '+233244771234')
        self.assertEqual(send.call_args.args[1]['template']['name'], 'receipt_ready')
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.customer_phone, '0244771234')

    def test_the_rules_say_it_can(self):
        self.assertIn('You CAN send receipts', boss.RULES)
