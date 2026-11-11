"""
A counter job finds its WhatsApp chat by phone number (Layer 2, Step 2.4a).
"""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.communications.models import Conversation
from apps.communications.services.job_link import chat_for, phones_of
from apps.communications.services.whatsapp_inbound import _receive
from apps.communications.tests import CommunicationsTestBase
from apps.spine import kinds
from apps.spine.jobs import record_job_created
from apps.spine.models import Visit
from apps.spine.recorder import record

PHONE = '233244123494'


def _customer(phone='0244123494', secondary=''):
    return SimpleNamespace(phone=phone, secondary_phone=secondary)


@override_settings(OCTOS_ASSISTANT_MODE='off')
@patch('apps.communications.services.whatsapp_inbound._keep_media')
@patch('apps.communications.assistant.counter.shop_open', return_value=True)
class JobLinkTests(CommunicationsTestBase):
    def _chat_with_files(self):
        _receive({'id': 'wamid.L1', 'from': PHONE, 'type': 'image',
                  'image': {'id': 'media-L1', 'mime_type': 'image/jpeg'}}, 'Ama')
        return Conversation.objects.get(contact_phone='+' + PHONE)

    def test_0244_and_plus233_are_the_same_number(self, _open, _media):
        self.assertEqual(phones_of(_customer('0244123494')), ['+233244123494'])

    def test_the_customers_open_chat_is_found_by_phone(self, _open, _media):
        chat = self._chat_with_files()
        self.assertEqual(chat_for(_customer('0244123494')), chat)

    def test_a_secondary_phone_finds_it_too(self, _open, _media):
        chat = self._chat_with_files()
        self.assertEqual(chat_for(_customer('0200000001', secondary='0244123494')), chat)

    def test_no_open_visit_no_link(self, _open, _media):
        self._chat_with_files()
        record(kinds.CONVERSATION_RESOLVED, conversation=Conversation.objects.get(contact_phone='+' + PHONE))
        self.assertIsNone(chat_for(_customer('0244123494')))

    def test_a_visit_quiet_for_hours_is_not_linked(self, _open, _media):
        self._chat_with_files()
        later = timezone.now() + timedelta(hours=3)
        self.assertIsNone(chat_for(_customer('0244123494'), now=later))

    def test_another_number_finds_nothing(self, _open, _media):
        self._chat_with_files()
        self.assertIsNone(chat_for(_customer('0209999999')))

    def test_a_new_job_carries_the_chat_and_closes_the_visit(self, _open, _media):
        chat = self._chat_with_files()
        job = SimpleNamespace(pk=901, job_number='WLB-TEST-1', job_type='INSTANT', status='DRAFT',
                              intake_channel='WALK_IN', intake_by=None, customer=None, branch=None)
        with patch('apps.spine.jobs._linked_chat', return_value=chat), \
                patch('apps.spine.jobs.record', wraps=None) as recorded:
            record_job_created(job)
        self.assertEqual(recorded.call_args.kwargs['conversation'], chat)
        self.assertEqual(recorded.call_args.kwargs['payload']['linked_to_chat_by'], 'phone')

    def test_a_failed_link_never_stops_the_job(self, _open, _media):
        job = SimpleNamespace(pk=902, job_number='WLB-TEST-2', job_type='INSTANT', status='DRAFT',
                              intake_channel='WALK_IN', intake_by=None, customer=_customer(), branch=None)
        with patch('apps.communications.services.job_link.link_new_job', side_effect=RuntimeError('boom')), \
                patch('apps.spine.jobs.record') as recorded:
            record_job_created(job)                     # no exception
        self.assertIsNone(recorded.call_args.kwargs['conversation'])
