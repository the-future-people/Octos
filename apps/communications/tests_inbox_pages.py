"""
The inbox reaches every chat (17 Nov 2026): a page at a time, back to the
first; search over all of them; chats that need a person first; and counts
over everything, not only the page loaded.
"""
from datetime import timedelta

from django.utils import timezone

from apps.communications.models import Conversation
from apps.communications.tests import CommunicationsTestBase, make_conversation

LIST = '/api/v1/communications/'


class InboxPagesTests(CommunicationsTestBase):

    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.chats = []
        for i in range(45):
            chat = make_conversation(None, contact_phone=f'+2332440{i:05d}', contact_name=f'Customer {i}')
            Conversation.objects.filter(pk=chat.pk).update(last_message_at=now - timedelta(hours=i))
            self.chats.append(chat)
        # The oldest chat waits for a person; one in the middle has unread messages.
        self.waiting = self.chats[-1]
        Conversation.objects.filter(pk=self.waiting.pk).update(
            handled_by=Conversation.STAFF, handoff_reason='Asked for a manager', handled_since=now - timedelta(minutes=9))
        Conversation.objects.filter(pk=self.chats[20].pk).update(unread_count=2, contact_name='Abena Oldchat')

    def test_forty_at_a_time_then_the_rest(self):
        first = self.client.get(LIST).data
        total = first['count']
        self.assertGreaterEqual(total, 45)
        self.assertEqual(len(first['results']), 40)
        self.assertIsNotNone(first['next'])
        second = self.client.get(LIST, {'page': 2}).data
        self.assertEqual(len(second['results']), total - 40)
        self.assertIsNone(second['next'])

    def test_a_chat_that_needs_a_person_comes_first_however_old(self):
        self.assertEqual(self.client.get(LIST).data['results'][0]['id'], self.waiting.pk)

    def test_then_the_newest(self):
        ids = [c['id'] for c in self.client.get(LIST).data['results']]
        self.assertEqual(ids[1:4], [self.chats[0].pk, self.chats[1].pk, self.chats[2].pk])

    def test_search_reaches_every_chat(self):
        found = self.client.get(LIST, {'search': 'oldchat'}).data['results']
        self.assertEqual([c['id'] for c in found], [self.chats[20].pk])

    def test_search_by_job_number(self):
        from apps.communications.tests import make_job
        job = make_job(self.branch)
        self.chats[30].jobs.add(job)
        found = self.client.get(LIST, {'search': job.job_number}).data['results']
        self.assertEqual([c['id'] for c in found], [self.chats[30].pk])

    def test_the_needs_you_filter(self):
        found = self.client.get(LIST, {'filter': 'needs'}).data['results']
        self.assertEqual([c['id'] for c in found], [self.waiting.pk])

    def test_counts_cover_every_chat(self):
        counts = self.client.get('/api/v1/communications/counts/').data
        self.assertEqual((counts['unread'], counts['needs']), (1, 1))
        self.assertEqual(counts['by_channel'].get('WHATSAPP'), 2)
        self.assertIsNotNone(counts['waiting_since'])
