"""
The counter after closing time, and files a person opened (11 Nov 2026).
"""
from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.communications.assistant import counter
from apps.communications.models import Conversation, Message
from apps.communications.services.opened import file_opened
from apps.communications.services.whatsapp_inbound import _receive
from apps.communications.tests import CommunicationsTestBase
from apps.spine import kinds
from apps.spine.models import Event, Visit
from apps.spine.obligations import files_handled

HOURS = 'apps.organization.services.hours'


def _local(hour, minute):
    today = timezone.localtime().date()
    return timezone.make_aware(datetime.combine(today, time(hour, minute)))


@patch(f'{HOURS}.hours_on', return_value=(time(7, 30), time(19, 30)))
@patch(f'{HOURS}.is_open', return_value=False)
class AttendedTests(CommunicationsTestBase):
    def setUp(self):
        super().setUp()
        self.branch.is_trading = True
        self.branch.save()
        cache.delete(counter.ATTENDED_KEY)

    def test_after_closing_with_an_attendant_at_the_screen_the_counter_is_open(self, _open, _hours):
        now = _local(19, 40)
        counter.mark_attended(now)
        self.assertTrue(counter.shop_open(now))

    def test_after_closing_with_nobody_at_the_screen_it_is_closed(self, _open, _hours):
        self.assertFalse(counter.shop_open(_local(19, 40)))

    def test_a_heartbeat_goes_stale_after_five_minutes(self, _open, _hours):
        counter.mark_attended(_local(19, 40))
        self.assertFalse(counter.shop_open(_local(19, 47)))

    def test_a_screen_left_on_overnight_does_not_open_the_counter(self, _open, _hours):
        counter.mark_attended(_local(23, 30))
        self.assertFalse(counter.shop_open(_local(23, 31)))

    def test_the_claim_strip_polling_is_the_heartbeat(self, _open, _hours):
        self.client.get('/api/v1/communications/arrivals/')
        self.assertTrue(counter.attended())


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
