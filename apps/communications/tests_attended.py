"""
The shop after closing time, and files a person opened (11 Nov 2026).

Closing up: past closing time, the counter stays alive until a cashier signs
off (the shop's own ritual), for at most 3 hours.
"""
from datetime import datetime, time
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.communications.assistant import counter, tools
from apps.communications.models import Message
from apps.communications.services.opened import file_opened
from apps.communications.services.whatsapp_inbound import _receive
from apps.communications.tests import CommunicationsTestBase
from apps.organization.services import shop_state
from apps.spine import kinds
from apps.spine.models import Event, Visit
from apps.spine.obligations import files_handled

HOURS = 'apps.organization.services.hours'
ON_POST = 'apps.organization.services.shop_state.cashier_on_post'


def _local(hour, minute):
    today = timezone.localtime().date()
    return timezone.make_aware(datetime.combine(today, time(hour, minute)))


@patch(f'{HOURS}.hours_on', return_value=(time(7, 30), time(19, 30)))
@patch(f'{HOURS}.is_open', return_value=False)
class ClosingUpTests(CommunicationsTestBase):
    def setUp(self):
        super().setUp()
        self.branch.is_trading = True
        self.branch.save()

    def test_after_closing_with_a_cashier_still_on_post_it_is_closing_up(self, _open, _hours):
        with patch(ON_POST, return_value=True):
            self.assertEqual(shop_state.state(self.branch, _local(19, 40)), shop_state.CLOSING)
            self.assertTrue(counter.shop_open(_local(19, 40)))

    def test_once_the_cashier_signs_off_it_is_closed(self, _open, _hours):
        with patch(ON_POST, return_value=False):
            self.assertEqual(shop_state.state(self.branch, _local(19, 40)), shop_state.CLOSED)
            self.assertFalse(counter.shop_open(_local(19, 40)))

    def test_a_forgotten_sign_off_does_not_keep_the_shop_open_at_night(self, _open, _hours):
        with patch(ON_POST, return_value=True):
            self.assertEqual(shop_state.state(self.branch, _local(23, 0)), shop_state.CLOSED)

    def test_branch_hours_tells_octos_it_is_closing_up_and_until_when(self, _open, _hours):
        with patch(ON_POST, return_value=True):
            said = tools.branch_hours(self.branch, at=_local(19, 40))
        self.assertTrue(said['closing_up'])
        self.assertIn('8', said['sort_by'])

    def test_branch_hours_when_closed_says_nothing_of_closing_up(self, _open, _hours):
        with patch(ON_POST, return_value=False):
            said = tools.branch_hours(self.branch, at=_local(19, 40))
        self.assertFalse(said['closing_up'])
        self.assertIsNone(said['sort_by'])


@override_settings(OCTOS_ASSISTANT_MODE='off')
@patch('apps.communications.services.whatsapp_inbound._keep_media')
@patch('apps.communications.assistant.counter.shop_open', return_value=True)
class FileOpenedTests(CommunicationsTestBase):
    def _photo(self):
        _receive({'id': 'wamid.O1', 'from': '233244123494', 'type': 'image',
                   'image': {'id': 'media-O1', 'mime_type': 'image/jpeg'}}, 'Ama')
        return Message.objects.get(external_id='wamid.O1')

    def test_opening_a_file_discharges_it(self, _open, _media):
        photo = self._photo()
        visit = Visit.objects.get(conversation=photo.conversation)
        self.assertFalse(files_handled(visit))
        file_opened(photo, self.user)
        self.assertTrue(files_handled(visit))

    def test_it_is_recorded_once_with_who_opened_it(self, _open, _media):
        photo = self._photo()
        file_opened(photo, self.user)
        file_opened(photo, self.user)
        event = Event.objects.get(kind=kinds.FILE_OPENED)
        self.assertEqual(event.actor_user, self.user)

    def test_octos_stays_quiet_on_more_files_once_one_was_opened(self, _open, _media):
        photo = self._photo()
        file_opened(photo, self.user)
        _receive({'id': 'wamid.O2', 'from': '233244123494', 'type': 'image',
                  'image': {'id': 'media-O2', 'mime_type': 'image/jpeg'}}, 'Ama')
        second = Message.objects.get(external_id='wamid.O2')
        said, why = counter.step(second.conversation, second, timezone.now())
        self.assertIsNone(said)
        self.assertIn('attendant', why)
