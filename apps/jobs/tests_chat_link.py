"""
A job recorded from a chat is linked to it (17 Nov 2026).

The create reply only echoed what was sent, with no id, so the screen's
follow-up "link this job to the chat" never ran. A customer writing from a
WhatsApp username (no number) then couldn't get their receipt: "This receipt
has no phone number to send it to." Now the job says which chat it came from
and is linked as it is made; and link_chat_jobs links the ones from before.
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.communications.models import Conversation
from apps.communications.services.chat_customer import chat_for
from apps.communications.tests import make_conversation
from apps.jobs.models import Job, PricingRule, Service
from apps.jobs.tests import JobsFixtureMixin
from apps.spine import kinds
from apps.spine.models import Event


@patch('apps.jobs.services.availability.can_make', return_value=True)
@patch('apps.finance.sheet_engine.SheetEngine.get_branch_lock_status',
       return_value={'can_create_jobs': True, 'lock_reason': ''})
class ChatLinkTests(JobsFixtureMixin, TestCase):

    URL = '/api/v1/jobs/create/'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.copy = Service.objects.create(name='Chat Link Copy', code='CHATCOPY', category='INSTANT',
                                          unit='PER_COPY', requires_design=False,
                                          requires_file_upload=False, is_active=True)
        PricingRule.objects.create(service=cls.copy, branch=None, base_price=Decimal('2.00'),
                                   color_multiplier=Decimal('1.00'), is_active=True)

    def setUp(self):
        # A customer writing from a username: no number, no customer record.
        self.chat = make_conversation(None, contact_phone='', contact_name='Ama')
        Conversation.objects.filter(pk=self.chat.pk).update(contact_user_id='GH.4417', contact_username='ama_prints')
        self.api = APIClient()
        self.api.force_authenticate(user=self.bm)

    def post(self, key, **extra):
        return self.api.post(self.URL, {
            'branch': self.branch.pk, 'idempotency_key': key,
            'line_items': [{'service': self.copy.pk, 'pages': 1, 'sets': 3}],
            **extra,
        }, format='json')

    def test_the_reply_says_which_job_was_made(self, *_):
        response = self.post('chat-link-001')
        self.assertEqual(response.status_code, 201, response.data)
        job = Job.objects.get(pk=response.data['id'])
        self.assertEqual(response.data['job_number'], job.job_number)

    def test_a_job_from_a_chat_is_linked_as_it_is_made(self, *_):
        response = self.post('chat-link-002', conversation=self.chat.pk)
        job = Job.objects.get(pk=response.data['id'])
        self.assertEqual(chat_for(job), self.chat)    # the receipt's way to the customer
        self.assertTrue(Event.objects.filter(kind=kinds.JOB_LINKED, job=job, conversation=self.chat).exists())

    def test_the_same_attempt_twice_links_once(self, *_):
        self.post('chat-link-003', conversation=self.chat.pk)
        self.post('chat-link-003', conversation=self.chat.pk)
        job = Job.objects.get(intake_by=self.bm)
        self.assertEqual(job.conversations.count(), 1)
        self.assertEqual(Event.objects.filter(kind=kinds.JOB_LINKED, job=job).count(), 1)

    def test_a_chat_that_does_not_exist_still_makes_the_job(self, *_):
        response = self.post('chat-link-004', conversation=999999)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(Job.objects.get(pk=response.data['id']).conversations.exists())

    def test_without_a_chat_nothing_is_linked(self, *_):
        response = self.post('chat-link-005')
        self.assertFalse(Job.objects.get(pk=response.data['id']).conversations.exists())


class LinkChatJobsCommandTests(JobsFixtureMixin, TestCase):

    def setUp(self):
        self.chat = make_conversation(None, contact_phone='', contact_name='Ama')
        Conversation.objects.filter(pk=self.chat.pk).update(contact_user_id='GH.4417', contact_username='ama_prints')
        self.job = Job.objects.create(branch=self.branch, job_type=Job.INSTANT, title='Photocopy',
                                      status=Job.PENDING_PAYMENT, estimated_cost=Decimal('6.00'),
                                      notes='For Ama (WhatsApp @ama_prints)')
        self.other = Job.objects.create(branch=self.branch, job_type=Job.INSTANT, title='Photocopy',
                                        status=Job.PENDING_PAYMENT, estimated_cost=Decimal('6.00'))

    def run_command(self, *args):
        out = StringIO()
        call_command('link_chat_jobs', *args, stdout=out)
        return out.getvalue()

    def test_it_lists_before_it_links(self):
        out = self.run_command()
        self.assertIn(self.job.job_number, out)
        self.assertFalse(self.job.conversations.exists())

    def test_apply_links_the_job_to_its_username_chat_only(self):
        self.run_command('--apply')
        self.assertEqual(chat_for(self.job), self.chat)
        self.assertFalse(self.other.conversations.exists())
