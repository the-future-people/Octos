"""
Who sees which conversation, and replies that really send.

Company conversations (the central WhatsApp number, no branch) are seen
by every branch. Another branch's conversation is refused on every
action, not just the list. A WhatsApp reply goes through the real sender,
and a shut window is refused with a reason staff can act on.
"""
from datetime import timedelta
from unittest.mock import patch

from rest_framework import status

from apps.communications.models import Message
from apps.communications.tests import CommunicationsTestBase, get_results, make_conversation
from apps.communications.tests_whatsapp_outbound import customer_wrote
from apps.organization.models import Branch

BASE = '/api/v1/communications'


class InboxAccessTests(CommunicationsTestBase):

    def setUp(self):
        super().setUp()
        self.company = make_conversation(None, contact_phone='+233244555001')
        other_branch = Branch.objects.create(name='OTB', code='OTB', region=self.branch.region)
        self.other = make_conversation(other_branch, contact_phone='+233244555002')

    # ── Seeing ──────────────────────────────────────────────────

    def test_company_conversations_are_listed_for_a_branch(self):
        ids = [c['id'] for c in get_results(self.client.get(self.url_list()))]
        self.assertIn(self.company.pk, ids)
        self.assertNotIn(self.other.pk, ids)

    def test_a_company_conversation_opens(self):
        res = self.client.get(self.url_detail(self.company.pk))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_another_branch_is_refused_on_every_action(self):
        for action in ('reply', 'assign', 'resolve', 'link-job'):
            res = self.client.post(f'{BASE}/{self.other.pk}/{action}/', {'body': 'x', 'user_id': self.user.pk})
            self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND, action)
        self.other.refresh_from_db()
        self.assertIsNone(self.other.assigned_to)
        self.assertNotEqual(self.other.status, 'RESOLVED')
        self.assertFalse(self.other.messages.exists())

    # ── Replying on WhatsApp ────────────────────────────────────

    def test_a_reply_inside_the_window_queues_a_real_send(self):
        customer_wrote(self.company, timedelta(minutes=10))
        with patch('apps.communications.tasks.deliver_whatsapp.delay') as delay:
            with self.captureOnCommitCallbacks(execute=True):
                res = self.client.post(self.url_reply(self.company.pk), {'body': 'Ready by 4pm 👍'})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        sent = self.company.messages.get(direction=Message.OUTBOUND)
        self.assertEqual(sent.status, Message.QUEUED)
        self.assertEqual(sent.sent_by, self.user)
        delay.assert_called_once_with(sent.pk)
        self.company.refresh_from_db()
        self.assertEqual(self.company.assigned_to, self.user)

    def test_a_shut_window_gives_the_reason_and_saves_nothing(self):
        res = self.client.post(self.url_reply(self.company.pk), {'body': 'Hello?'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("hasn't written", res.data['detail'])
        self.assertFalse(self.company.messages.filter(direction=Message.OUTBOUND).exists())
        self.company.refresh_from_db()
        self.assertIsNone(self.company.assigned_to)

    def test_an_internal_note_needs_no_window(self):
        res = self.client.post(self.url_reply(self.company.pk), {'body': 'Customer prefers mornings', 'is_internal_note': True})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        note = self.company.messages.get()
        self.assertEqual(note.channel, Message.SYSTEM)
        self.assertTrue(note.is_internal_note)