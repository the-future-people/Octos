"""
Customer chats of 25 and 26 Nov 2026, reviewed with Khofi: "Wooow thank
you" is a goodbye; a file still on its way from WhatsApp is waited for, not
called missing; arriving mid-chat isn't asked for the files again; and a
second job for an order already waiting at the counter is caught.
"""
from datetime import timedelta
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.communications.assistant import brain, counter
from apps.communications.models import Message
from apps.communications.tests import make_conversation, make_org
from apps.jobs.models import Job
from apps.jobs.services import counter_orders
from apps.jobs.tests_counter_orders import CounterBase


def said(body, direction=Message.INBOUND):
    return SimpleNamespace(body=body, direction=direction, media_id='', message_type='TEXT')


class WowTests(TestCase):

    def test_wooow_thank_you_after_a_receipt_closes(self):
        receipt = said('Hello Angela, here is your receipt for GHS 123.00.', Message.OUTBOUND)
        self.assertTrue(brain.closed_after([said('Wooow thank you.'), receipt]))
        self.assertTrue(brain.closed_after([said('Awesome, thanks'), receipt]))

    def test_a_question_is_still_a_question(self):
        receipt = said('Hello Angela, here is your receipt for GHS 123.00.', Message.OUTBOUND)
        self.assertFalse(brain.closed_after([said('Wow, can you also laminate it?'), receipt]))


class FileOnItsWayTests(TestCase):

    def setUp(self):
        self.conv = make_conversation(None, contact_phone='+233244800069', contact_name='Fiifi')

    def sent(self, **fields):
        return Message.objects.create(conversation=self.conv, direction=Message.INBOUND, channel=Message.WHATSAPP,
                                      message_type=Message.DOCUMENT, media_id='m-26', media_name='Practical.pdf',
                                      **fields)

    def test_octos_waits_for_a_file_still_arriving(self):
        from apps.communications.services import whatsapp_inbound
        from unittest.mock import patch
        message = self.sent()
        with patch('apps.communications.tasks.fetch_whatsapp_media.delay'):
            whatsapp_inbound._keep_media(message)
        self.assertTrue(brain._still_reading(self.conv.pk))

    def test_not_for_one_that_failed_or_is_old(self):
        failed = self.sent(media_info={'failed': 'network'})
        self.assertFalse(brain._still_reading(self.conv.pk))
        failed.delete()
        old = self.sent(media_info={'fetching': True})
        Message.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(minutes=4))
        self.assertFalse(brain._still_reading(self.conv.pk))


class MidChatWelcomeTests(TestCase):

    def setUp(self):
        self.branch = make_org()
        self.conv = make_conversation(None, contact_phone='+233244806077', contact_name='Grace')

    def test_a_file_already_sent_is_not_asked_for_again(self):
        Message.objects.create(conversation=self.conv, direction=Message.INBOUND, channel=Message.WHATSAPP,
                               message_type=Message.IMAGE, media_id='m-g1')
        text = counter.ack_text(self.conv, self.branch)
        self.assertIn('The attendant has your file and our chat', text)
        self.assertNotIn('Hand your files', text)

    def test_no_files_yet_asks_for_them(self):
        self.assertIn('Hand your files to the attendant', counter.ack_text(self.conv, self.branch))


class WaitingAtTheCounterTests(CounterBase):

    def waiting_job(self):
        from apps.customers.models import CustomerProfile
        ama = CustomerProfile.objects.create(first_name='Ama', phone='+233244000731', customer_type='INDIVIDUAL')
        job = counter_orders.reserve(self.order(), self.chat)
        Job.objects.filter(pk=job.pk).update(customer=ama)
        job.refresh_from_db()
        return job, ama

    def test_the_job_screen_hears_of_it_and_a_new_job_replaces_it(self):
        job, ama = self.waiting_job()
        api = APIClient()
        api.force_authenticate(self.esi)
        found = api.get('/api/v1/jobs/desk/waiting-for/', {'customer': ama.pk}).json()['jobs']
        self.assertEqual([j['counter']['code'] for j in found], [job.counter_code])
        replaced = api.post(f'/api/v1/jobs/{job.pk}/desk/replace/')
        self.assertEqual(replaced.status_code, 200, replaced.content)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.CANCELLED)
        self.assertEqual(api.get('/api/v1/jobs/desk/waiting-for/', {'customer': ama.pk}).json()['jobs'], [])
        self.assertEqual(api.post(f'/api/v1/jobs/{job.pk}/desk/replace/').status_code, 409)  # not waiting any more
