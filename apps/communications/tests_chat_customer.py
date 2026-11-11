"""
A job's customer from its WhatsApp chat, and the link closing the visit (Layer 2, Step 2.4b).
"""
from unittest.mock import patch

from django.test import override_settings

from apps.communications.models import Conversation
from apps.communications.services.chat_customer import customer_for_chat
from apps.communications.services.whatsapp_inbound import _receive
from apps.communications.tests import CommunicationsTestBase, make_conversation
from apps.customers.models import CustomerProfile
from apps.spine import kinds
from apps.spine.models import Event, Visit
from apps.spine.obligations import files_handled

PHONE = '233244123494'


class ChatCustomerTests(CommunicationsTestBase):
    def test_an_unregistered_chat_gets_a_light_record(self):
        chat = make_conversation(self.branch, contact_phone='+233244111222', contact_name='Ama Owusu')
        customer, created = customer_for_chat(chat)
        self.assertTrue(created)
        self.assertEqual(customer.first_name, 'Ama')
        self.assertTrue(customer.phone.endswith('244111222'))
        chat.refresh_from_db()
        self.assertEqual(chat.customer, customer)

    def test_asking_twice_makes_one_record(self):
        chat = make_conversation(self.branch, contact_phone='+233244111223', contact_name='Kofi')
        first, _ = customer_for_chat(chat)
        chat.refresh_from_db()
        second, created = customer_for_chat(chat)
        self.assertEqual(first, second)
        self.assertFalse(created)

    def test_an_existing_customer_with_the_number_written_locally_is_found(self):
        existing = CustomerProfile.objects.create(phone='0244111224', first_name='Efua')
        chat = make_conversation(self.branch, contact_phone='+233244111224', contact_name='E')
        customer, created = customer_for_chat(chat)
        self.assertEqual(customer, existing)
        self.assertFalse(created)

    def test_a_username_chat_with_no_number_gets_none(self):
        chat = make_conversation(self.branch, contact_phone='', contact_name='Yaw')
        self.assertEqual(customer_for_chat(chat), (None, False))

    def test_the_endpoint_returns_the_customer(self):
        chat = make_conversation(self.branch, contact_phone='+233244111225', contact_name='Abena')
        response = self.client.post(f'/api/v1/communications/{chat.pk}/customer/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['created'])
        self.assertTrue(response.json()['phone'].endswith('244111225'))


@override_settings(OCTOS_ASSISTANT_MODE='off')
@patch('apps.communications.services.whatsapp_inbound._keep_media')
@patch('apps.communications.assistant.counter.shop_open', return_value=True)
class LinkJobTests(CommunicationsTestBase):
    def _chat_with_files(self):
        _receive({'id': 'wamid.J1', 'from': PHONE, 'type': 'image',
                  'image': {'id': 'media-J1', 'mime_type': 'image/jpeg'}}, 'Ama')
        return Conversation.objects.get(contact_phone='+' + PHONE)

    def _job(self):
        from apps.jobs.models import Job
        job = Job.objects.filter(branch=self.branch).first()
        if job is None:
            self.skipTest('no job fixture available in this test base')
        return job

    def test_linking_a_job_closes_the_visit_and_handles_the_files(self, _open, _media):
        chat = self._chat_with_files()
        job = self._job()
        response = self.client.post(f'/api/v1/communications/{chat.pk}/link-job/', {'job_id': job.pk},
                                    format='json')
        self.assertEqual(response.status_code, 200)
        visit = Visit.objects.get(conversation=chat)
        self.assertEqual(visit.outcome, 'JOB_CREATED')
        self.assertTrue(files_handled(visit))
        self.assertTrue(Event.objects.filter(kind=kinds.JOB_LINKED, conversation=chat).exists())

    def test_the_old_job_key_still_links_instead_of_unlinking(self, _open, _media):
        chat = self._chat_with_files()
        job = self._job()
        self.client.post(f'/api/v1/communications/{chat.pk}/link-job/', {'job': job.pk}, format='json')
        self.assertIn(job, chat.jobs.all())
