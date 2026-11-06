"""
Who answers a conversation: Octos, or a person.

The buttons, a reply taking over, an internal note not taking over, Octos
handing over with a reason, and the watch: a waiting customer gets the
person reminded at 30 minutes, and Octos takes back 10 minutes after an
ignored reminder.
"""
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from rest_framework import status

from apps.communications.models import Conversation, Message
from apps.communications.services import handover
from apps.communications.tests import CommunicationsTestBase, make_conversation
from apps.communications.tests_whatsapp_outbound import customer_wrote
from apps.organization.models import Branch

BASE = '/api/v1/communications'


class HandoverTests(CommunicationsTestBase):

    def setUp(self):
        super().setUp()
        self.conv = make_conversation(None, contact_phone='+233244555101')
        alerts = patch('apps.notifications.services.notify_many')
        self.alerts = alerts.start()
        self.addCleanup(alerts.stop)

    def notes(self):
        return list(self.conv.messages.filter(is_internal_note=True).values_list('body', flat=True))

    def staff_has_it(self, waited, reminded=None):
        """A person has the conversation; the customer wrote `waited` ago."""
        customer_wrote(self.conv, waited)
        Conversation.objects.filter(pk=self.conv.pk).update(
            handled_by=Conversation.STAFF, assigned_to=self.user,
            reminded_at=(timezone.now() - reminded) if reminded else None,
        )
        self.conv.refresh_from_db()

    # ── The buttons ─────────────────────────────────────────────

    def test_take_over_quiets_octos_and_says_who(self):
        res = self.client.post(f'{BASE}/{self.conv.pk}/take-over/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.handled_by, Conversation.STAFF)
        self.assertEqual(self.conv.assigned_to, self.user)
        self.assertEqual(len(self.notes()), 1)
        self.assertIn('took over', self.notes()[0])

    def test_pressing_take_over_twice_changes_nothing_more(self):
        self.client.post(f'{BASE}/{self.conv.pk}/take-over/')
        self.client.post(f'{BASE}/{self.conv.pk}/take-over/')
        self.assertEqual(len(self.notes()), 1)

    def test_hand_back_returns_it_to_octos(self):
        self.client.post(f'{BASE}/{self.conv.pk}/take-over/')
        res = self.client.post(f'{BASE}/{self.conv.pk}/hand-back/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.handled_by, Conversation.OCTOS)
        self.assertIn('handed the conversation back', self.notes()[-1])

    def test_another_branchs_conversation_cant_be_taken(self):
        other = Branch.objects.create(name='OTB', code='OTB', region=self.branch.region)
        theirs = make_conversation(other, contact_phone='+233244555102')
        for action in ('take-over', 'hand-back'):
            self.assertEqual(self.client.post(f'{BASE}/{theirs.pk}/{action}/').status_code,
                             status.HTTP_404_NOT_FOUND)

    def test_an_internal_note_does_not_take_over(self):
        self.client.post(f'{BASE}/{self.conv.pk}/reply/', {'body': 'Prefers mornings', 'is_internal_note': True})
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.handled_by, Conversation.OCTOS)

    # ── Octos handing over ──────────────────────────────────────

    def test_octos_hands_over_with_a_reason_and_alerts(self):
        handover.octos_hands_over(self.conv, 'customer asked to be called')
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.handled_by, Conversation.STAFF)
        self.assertEqual(self.conv.handoff_reason, 'customer asked to be called')
        self.assertIn('Needs you', self.alerts.call_args.kwargs['message'])

    def test_taking_over_after_octos_asked_clears_the_reason(self):
        handover.octos_hands_over(self.conv, 'complaint about sticker size')
        self.client.post(f'{BASE}/{self.conv.pk}/take-over/')
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.handoff_reason, '')

    # ── The watch ───────────────────────────────────────────────

    def test_a_customer_waiting_30_minutes_gets_the_person_reminded(self):
        self.staff_has_it(waited=timedelta(minutes=31))
        self.assertEqual(handover.watch(), (1, 0))
        self.conv.refresh_from_db()
        self.assertIsNotNone(self.conv.reminded_at)
        self.assertIn('waited 31 minutes', self.alerts.call_args.kwargs['message'])

    def test_20_minutes_is_not_yet_a_reminder(self):
        self.staff_has_it(waited=timedelta(minutes=20))
        self.assertEqual(handover.watch(), (0, 0))

    def test_an_ignored_reminder_hands_it_back_to_octos(self):
        self.staff_has_it(waited=timedelta(minutes=45), reminded=timedelta(minutes=11))
        self.assertEqual(handover.watch(), (0, 1))
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.handled_by, Conversation.OCTOS)
        self.assertIn('Octos took the conversation back', self.notes()[-1])

    def test_a_reminder_only_9_minutes_old_waits(self):
        self.staff_has_it(waited=timedelta(minutes=45), reminded=timedelta(minutes=9))
        self.assertEqual(handover.watch(), (0, 0))

    def test_nobody_waiting_means_nothing_to_watch(self):
        self.staff_has_it(waited=timedelta(minutes=45))
        Message.objects.create(conversation=self.conv, direction=Message.OUTBOUND,
                               channel=Message.WHATSAPP, body='On it', sent_by=self.user)
        self.assertEqual(handover.watch(), (0, 0))

    def test_a_staff_reply_clears_the_reminder(self):
        self.staff_has_it(waited=timedelta(minutes=45), reminded=timedelta(minutes=5))
        handover.staff_replied(self.conv, self.user)
        self.conv.refresh_from_db()
        self.assertIsNone(self.conv.reminded_at)

    def test_a_staff_reply_takes_over_from_octos_waiting_for_a_person(self):
        handover.octos_hands_over(self.conv, 'customer asked to be called')
        handover.staff_replied(self.conv, self.user)
        self.conv.refresh_from_db()
        self.assertEqual((self.conv.handled_by, self.conv.handoff_reason), (Conversation.STAFF, ''))
    
    def test_resolving_clears_needs_you_and_returns_it_to_octos(self):
        handover.octos_hands_over(self.conv, 'customer asked to be called')
        self.client.post(f'{BASE}/{self.conv.pk}/resolve/')
        self.conv.refresh_from_db()
        self.assertEqual((self.conv.status, self.conv.handled_by, self.conv.handoff_reason),
                         (Conversation.RESOLVED, Conversation.OCTOS, ''))