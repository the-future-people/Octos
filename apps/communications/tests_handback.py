"""
A person's hand-back is "I've dealt with it" (11 Nov 2026).

Kings Hub, 11 Nov: the customer asked for a call, a person took over, called
them, and handed back; Octos then answered the old request ("I've let the team
know you're happy with a call... they'll call you then"). It must not.
"""
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.communications.assistant import brain
from apps.communications.models import Message
from apps.communications.services import handover
from apps.communications.tests import CommunicationsTestBase, make_conversation

WAKE = 'apps.communications.services.whatsapp_inbound.wake_octos'


@override_settings(ANTHROPIC_API_KEY='test-key')
class HandBackTests(CommunicationsTestBase):
    def setUp(self):
        super().setUp()
        self.chat = make_conversation(self.branch, contact_phone='+233244000555')
        closed = patch('apps.communications.assistant.counter.shop_open', return_value=False)
        closed.start()
        self.addCleanup(closed.stop)

    def _customer(self, body):
        return Message.objects.create(conversation=self.chat, direction=Message.INBOUND,
                                      channel=Message.WHATSAPP, body=body)

    def test_a_persons_hand_back_does_not_wake_octos(self):
        self._customer('Please can someone call me?')
        handover.take_over(self.chat, self.user)
        with patch(WAKE) as wake, self.captureOnCommitCallbacks(execute=True):
            handover.hand_back(self.chat, self.user)
        wake.assert_not_called()

    def test_octos_taking_back_still_answers_a_waiting_customer(self):
        self._customer('Hello? Anyone there?')
        handover.take_over(self.chat, self.user)
        with patch(WAKE) as wake, self.captureOnCommitCallbacks(execute=True):
            handover.hand_back(self.chat, None, why='nobody answered the reminder')
        wake.assert_called_once()

    def test_a_run_queued_before_the_hand_back_stays_silent(self):
        asked = self._customer('Please can someone call me?')
        handover.take_over(self.chat, self.user)
        handover.hand_back(self.chat, self.user)
        self.chat.refresh_from_db()
        self.assertEqual(brain._silence(self.chat, asked, timezone.now()),
                         'a person dealt with this before handing it back')

    def test_a_new_message_after_the_hand_back_is_answered(self):
        self._customer('Please can someone call me?')
        handover.take_over(self.chat, self.user)
        handover.hand_back(self.chat, self.user)
        new = self._customer('Thanks! One more thing, how much is A3 colour?')
        self.chat.refresh_from_db()
        self.assertIsNone(brain._silence(self.chat, new, timezone.now()))
