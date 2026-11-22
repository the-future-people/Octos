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
