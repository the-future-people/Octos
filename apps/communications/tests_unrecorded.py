"""
Files opened, no job recorded: the BM's list before closing the day (Layer 2, Step 2.4b).
"""
from unittest.mock import patch

from django.test import override_settings

from apps.communications.models import Conversation, Message
from apps.communications.services.opened import file_opened
from apps.communications.services.whatsapp_inbound import _receive
from apps.communications.tests import CommunicationsTestBase
from apps.spine import kinds
from apps.spine.models import Event
from apps.spine.recorder import record
from apps.spine.unrecorded import unrecorded_files

PHONE = '233244123494'


@override_settings(OCTOS_ASSISTANT_MODE='off')
@patch('apps.communications.services.whatsapp_inbound._keep_media')
@patch('apps.communications.assistant.counter.shop_open', return_value=True)
class UnrecordedTests(CommunicationsTestBase):
    def _opened_photo(self):
        _receive({'id': 'wamid.U1', 'from': PHONE, 'type': 'image',
                  'image': {'id': 'media-U1', 'mime_type': 'image/jpeg'}}, 'Ama')
        photo = Message.objects.get(external_id='wamid.U1')
        file_opened(photo, self.user)
        return Conversation.objects.get(contact_phone='+' + PHONE)

    def test_files_opened_with_no_job_are_listed_with_who_opened_them(self, _open, _media):
        self._opened_photo()
        [row] = unrecorded_files()
        self.assertEqual(row['name'], 'Ama')
        self.assertEqual(row['number_tail'], '494')
        self.assertEqual(row['files_opened'], 1)
        self.assertEqual(len(row['opened_by']), 1)

    def test_a_job_linked_to_the_chat_clears_it(self, _open, _media):
        chat = self._opened_photo()
        record(kinds.JOB_LINKED, actor=Event.STAFF, conversation=chat)
        self.assertEqual(unrecorded_files(), [])

    def test_a_job_made_for_the_chat_clears_it(self, _open, _media):
        chat = self._opened_photo()
        record(kinds.JOB_CREATED, actor=Event.STAFF, conversation=chat)
        self.assertEqual(unrecorded_files(), [])

    def test_files_nobody_opened_are_not_listed(self, _open, _media):
        _receive({'id': 'wamid.U2', 'from': PHONE, 'type': 'image',
                  'image': {'id': 'media-U2', 'mime_type': 'image/jpeg'}}, 'Ama')
        self.assertEqual(unrecorded_files(), [])
