"""
What the inbox screen reads: the folder chip in the list, the job card
and the free-reply window in the open conversation, and media ids on
messages.
"""
from datetime import timedelta
from decimal import Decimal

from apps.communications.models import Message
from apps.communications.tests import CommunicationsTestBase, make_conversation, make_job
from apps.communications.tests_whatsapp_outbound import customer_wrote
from apps.jobs.models import Job

BASE = '/api/v1/communications'


class InboxPayloadTests(CommunicationsTestBase):

    def setUp(self):
        super().setUp()
        self.conv = make_conversation(None, contact_phone='+233244600601')
        self.job = make_job(self.branch)
        self.job.title = 'SAV stickers'
        self.job.work_state = Job.Work.IN_PRODUCTION
        self.job.estimated_cost = Decimal('50.00')
        self.job.amount_paid = Decimal('20.00')
        self.job.save()
        self.conv.jobs.add(self.job)

    def rows(self):
        data = self.client.get(f'{BASE}/').data
        return data['results'] if isinstance(data, dict) else data

    def test_the_list_carries_the_folder_chip(self):
        row = next(r for r in self.rows() if r['id'] == self.conv.pk)
        self.assertEqual(row['job']['id'], self.job.pk)
        self.assertTrue(row['job']['ref'])

    def test_the_job_card_says_what_octos_would_say(self):
        card = self.client.get(f'{BASE}/{self.conv.pk}/').data['job_card']
        self.assertEqual(card['stage'], 'being made now')
        self.assertEqual(card['balance_due'], 'GHS 30.00')

    def test_the_free_reply_window_follows_the_customers_last_message(self):
        self.assertIsNone(self.client.get(f'{BASE}/{self.conv.pk}/').data['window_closes_at'])
        customer_wrote(self.conv, timedelta(minutes=5))
        self.assertIsNotNone(self.client.get(f'{BASE}/{self.conv.pk}/').data['window_closes_at'])

    def test_messages_carry_their_media_id(self):
        Message.objects.create(conversation=self.conv, direction=Message.INBOUND,
                               channel=Message.WHATSAPP, message_type=Message.DOCUMENT,
                               body='', media_id='media-123')
        messages = self.client.get(f'{BASE}/{self.conv.pk}/').data['messages']
        self.assertEqual(messages[-1]['media_id'], 'media-123')