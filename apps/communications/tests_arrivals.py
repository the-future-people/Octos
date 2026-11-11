"""
Files arriving now, for the attendant's Claim strip (Layer 2, Step 2.3).
"""
from unittest.mock import patch

from django.test import override_settings

from apps.communications.models import Conversation
from apps.communications.services.whatsapp_inbound import _receive
from apps.communications.tests import CommunicationsTestBase
from apps.spine import kinds
from apps.spine.arrivals import arrivals
from apps.spine.models import Event
from apps.spine.recorder import record


PHONE = '233244123494'


def _chat():
    # The base class makes a conversation of its own, so find this customer's by number.
    return Conversation.objects.get(contact_phone='+' + PHONE)


def _photo(wamid, phone=PHONE):
    return {'id': wamid, 'from': phone, 'type': 'image',
            'image': {'id': f'media-{wamid}', 'mime_type': 'image/jpeg'}}


@override_settings(OCTOS_ASSISTANT_MODE='off')
@patch('apps.communications.services.whatsapp_inbound._keep_media')
@patch('apps.communications.assistant.counter.shop_open', return_value=True)
class ArrivalsTests(CommunicationsTestBase):

    def test_files_nobody_has_picked_up_are_listed(self, _open, _media):
        _receive(_photo('wamid.A1'), 'Ama')
        _receive(_photo('wamid.A2'), 'Ama')
        [row] = arrivals()
        self.assertEqual(len(row['files']), 2)
        self.assertEqual(row['number_tail'], '494')
        self.assertEqual(row['name'], 'Ama')

    def test_claimed_files_drop_off(self, _open, _media):
        _receive(_photo('wamid.B1'), 'Kwame')
        chat = _chat()
        record(kinds.COUNTER_CLAIMED, actor=Event.STAFF, conversation=chat)
        self.assertEqual(arrivals(), [])

    def test_a_job_made_from_them_drops_off(self, _open, _media):
        _receive(_photo('wamid.C1'), 'Efua')
        record(kinds.JOB_CREATED, actor=Event.STAFF, conversation=_chat())
        self.assertEqual(arrivals(), [])

    def test_words_alone_are_not_an_arrival(self, _open, _media):
        _receive({'id': 'wamid.D1', 'from': '233244123495', 'type': 'text',
                  'text': {'body': 'How much is A4 colour?'}}, 'Yaw')
        self.assertEqual(arrivals(), [])

    def test_the_view_lists_them_for_staff(self, _open, _media):
        _receive(_photo('wamid.E1'), 'Ama')
        response = self.client.get('/api/v1/communications/arrivals/')
        self.assertEqual(response.status_code, 200)
        [row] = response.json()
        self.assertEqual(row['number_tail'], '494')
        self.assertEqual(len(row['files']), 1)
        self.assertIn('presence', row)
