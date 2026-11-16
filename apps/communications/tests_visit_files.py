"""
A file that opens a visit belongs to that visit (16 Nov 2026).

Record a job from the chat offers "this visit's files": messages from when
the visit opened. The visit used to open at the moment its event was
recorded, a few milliseconds after the message itself was saved, so a
customer whose first message was the file (Kwabena, 16 Nov) had no files to
offer. The event now carries the message's own time.
"""
from unittest.mock import patch

from django.test import override_settings

from apps.communications.api.serializers import ConversationDetailSerializer
from apps.communications.models import Conversation, Message
from apps.communications.services.whatsapp_inbound import _receive
from apps.communications.tests import CommunicationsTestBase
from apps.spine.models import Visit

PHONE = '233244123495'


@override_settings(OCTOS_ASSISTANT_MODE='off')
@patch('apps.communications.services.whatsapp_inbound._keep_media')
@patch('apps.communications.assistant.counter.shop_open', return_value=True)
class VisitFilesTests(CommunicationsTestBase):

    def test_a_file_sent_first_is_inside_its_own_visit(self, _open, _media):
        _receive({'id': 'wamid.VF1', 'from': PHONE, 'type': 'document',
                  'document': {'id': 'media-VF1', 'mime_type': 'application/pdf', 'filename': 'African_Studies.pdf'}},
                 'Kwabena')
        chat = Conversation.objects.get(contact_phone='+' + PHONE)
        message = Message.objects.get(external_id='wamid.VF1')
        visit = Visit.objects.get(conversation=chat)
        self.assertEqual(visit.opened_at, message.created_at)
        started = ConversationDetailSerializer(chat).data['visit_started_at']
        self.assertLessEqual(started, message.created_at)
