"""
Tests for the Communications API.

Coverage:
  - ConversationListView      — list, branch scoping, filters, search
  - ConversationDetailView    — detail, unread reset, branch isolation
  - ConversationReplyView     — reply, auto-claim, internal note, validation
  - ConversationAssignView    — assign, reassign, bad user, missing field
  - ConversationResolveView   — resolve, already resolved guard, 404
  - ConversationLinkJobView   — link, unlink, bad job, bad conversation

Run:
  python manage.py test apps.communications.tests --verbosity=2
"""

import uuid
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import CustomUser
from apps.organization.models import Belt, Region, Branch
from apps.communications.models import Conversation, Message


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def make_org(suffix=''):
    belt   = Belt.objects.create(name=f'Southern Belt{suffix}')
    region = Region.objects.create(name=f'Accra Region{suffix}', belt=belt)
    branch = Branch.objects.create(name=f'NTB{suffix}', code=f'NTB{suffix}', region=region)
    return branch


def make_user(email, branch, password='pass1234'):
    """
    Create a user with a unique employee_id to avoid the unique constraint
    on that field when creating multiple users in the same test run.
    """
    user = CustomUser.objects.create_user(
        email=email,
        password=password,
        first_name='Test',
        last_name='User',
        employee_id=str(uuid.uuid4())[:20],  # unique per call
    )
    user.branch = branch
    user.save()
    return user


def make_conversation(branch, channel=Conversation.WHATSAPP, **kwargs):
    defaults = dict(
        contact_name='Kwame Mensah',
        contact_phone='+233244000001',
        status=Conversation.OPEN,
    )
    defaults.update(kwargs)
    return Conversation.objects.create(branch=branch, channel=channel, **defaults)


def make_job(branch):
    from apps.jobs.models import Job
    return Job.objects.create(branch=branch, status='PENDING')


def get_results(res):
    """
    DRF list responses may be paginated { count, results: [...] }
    or plain lists. Handle both.
    """
    if isinstance(res.data, list):
        return res.data
    return res.data.get('results', res.data)


# ─────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────

class CommunicationsTestBase(TestCase):

    def setUp(self):
        self.branch = make_org()
        self.user   = make_user('agent@octos.test', self.branch)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.convo  = make_conversation(self.branch)

    def url_list(self):
        return reverse('conversation-list')

    def url_detail(self, pk):
        return reverse('conversation-detail', args=[pk])

    def url_reply(self, pk):
        return reverse('conversation-reply', args=[pk])

    def url_assign(self, pk):
        return reverse('conversation-assign', args=[pk])

    def url_resolve(self, pk):
        return reverse('conversation-resolve', args=[pk])

    def url_link_job(self, pk):
        return reverse('conversation-link-job', args=[pk])


# ─────────────────────────────────────────────────────────────
# List
# ─────────────────────────────────────────────────────────────

class ConversationListTests(CommunicationsTestBase):

    def test_list_returns_200(self):
        res = self.client.get(self.url_list())
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_list_requires_auth(self):
        self.client.logout()
        res = self.client.get(self.url_list())
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_scoped_to_users_branch(self):
        other_branch = Branch.objects.create(
            name='WLB', code='WLB', region=self.branch.region
        )
        make_conversation(other_branch, contact_phone='+233244000099')

        results = get_results(self.client.get(self.url_list()))
        ids = [c['id'] for c in results]
        self.assertIn(self.convo.id, ids)
        self.assertFalse(any(c['id'] != self.convo.id for c in results),
                         'Conversations from other branches should not appear')

    def test_list_contains_display_name(self):
        results = get_results(self.client.get(self.url_list()))
        self.assertTrue(len(results) > 0)
        self.assertIn('display_name', results[0])

    def test_list_filter_by_channel(self):
        make_conversation(
            self.branch, channel=Conversation.EMAIL,
            contact_phone='', contact_email='k@test.com',
            contact_name='Email User'
        )
        results = get_results(self.client.get(self.url_list(), {'channel': 'EMAIL'}))
        self.assertTrue(len(results) >= 1)
        self.assertTrue(all(c['channel'] == 'EMAIL' for c in results))

    def test_list_filter_by_status(self):
        self.convo.status = Conversation.RESOLVED
        self.convo.save()
        results = get_results(self.client.get(self.url_list(), {'status': 'RESOLVED'}))
        self.assertTrue(all(c['status'] == 'RESOLVED' for c in results))

    def test_list_search_by_contact_name(self):
        # Create a uniquely named conversation to search for
        make_conversation(
            self.branch,
            contact_phone='+233244999888',
            contact_name='ZZZ Unique Name',
        )
        results = get_results(self.client.get(self.url_list(), {'search': 'ZZZ Unique'}))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['display_name'], 'ZZZ Unique Name')


# ─────────────────────────────────────────────────────────────
# Detail
# ─────────────────────────────────────────────────────────────

class ConversationDetailTests(CommunicationsTestBase):

    def test_detail_returns_200(self):
        res = self.client.get(self.url_detail(self.convo.pk))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_detail_contains_messages_array(self):
        res = self.client.get(self.url_detail(self.convo.pk))
        self.assertIn('messages', res.data)
        self.assertIsInstance(res.data['messages'], list)

    def test_detail_resets_unread_count(self):
        self.convo.unread_count = 5
        self.convo.save()
        self.client.get(self.url_detail(self.convo.pk))
        self.convo.refresh_from_db()
        self.assertEqual(self.convo.unread_count, 0)

    def test_detail_404_for_other_branch(self):
        other_branch = Branch.objects.create(
            name='WLB2', code='WLB2', region=self.branch.region
        )
        other_convo = make_conversation(other_branch, contact_phone='+233244000088')
        res = self.client.get(self.url_detail(other_convo.pk))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


# ─────────────────────────────────────────────────────────────
# Reply
# ─────────────────────────────────────────────────────────────

class ConversationReplyTests(CommunicationsTestBase):

    def test_reply_creates_message(self):
        res = self.client.post(self.url_reply(self.convo.pk), {'body': 'Hello!'})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            Message.objects.filter(conversation=self.convo, is_internal_note=False).count(), 1
        )

    def test_reply_direction_is_outbound(self):
        self.client.post(self.url_reply(self.convo.pk), {'body': 'Hi there'})
        msg = Message.objects.filter(conversation=self.convo, is_internal_note=False).first()
        self.assertEqual(msg.direction, Message.OUTBOUND)

    def test_reply_sets_sent_by(self):
        self.client.post(self.url_reply(self.convo.pk), {'body': 'Hi there'})
        msg = Message.objects.filter(conversation=self.convo, is_internal_note=False).first()
        self.assertEqual(msg.sent_by, self.user)

    def test_reply_auto_claims_unassigned_conversation(self):
        self.assertIsNone(self.convo.assigned_to)
        self.client.post(self.url_reply(self.convo.pk), {'body': 'Claiming this'})
        self.convo.refresh_from_db()
        self.assertEqual(self.convo.assigned_to, self.user)

    def test_reply_does_not_overwrite_existing_assignment(self):
        other = make_user('other@octos.test', self.branch)
        self.convo.assigned_to = other
        self.convo.save()
        self.client.post(self.url_reply(self.convo.pk), {'body': 'Reply'})
        self.convo.refresh_from_db()
        self.assertEqual(self.convo.assigned_to, other)

    def test_reply_updates_last_message_preview(self):
        self.client.post(self.url_reply(self.convo.pk), {'body': 'Preview test'})
        self.convo.refresh_from_db()
        self.assertEqual(self.convo.last_message_preview, 'Preview test')

    def test_reply_requires_body(self):
        # Empty string body should fail — body field must not be blank
        res = self.client.post(
            self.url_reply(self.convo.pk),
            data='{"body": ""}',
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reply_404_unknown_conversation(self):
        res = self.client.post(self.url_reply(99999), {'body': 'Hello'})
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_internal_note_uses_system_channel(self):
        self.client.post(self.url_reply(self.convo.pk), {
            'body': 'Internal only',
            'is_internal_note': True,
        })
        msg = Message.objects.filter(
            conversation=self.convo, is_internal_note=True
        ).first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.channel, Message.SYSTEM)


# ─────────────────────────────────────────────────────────────
# Assign
# ─────────────────────────────────────────────────────────────

class ConversationAssignTests(CommunicationsTestBase):

    def setUp(self):
        super().setUp()
        self.agent = make_user('agent2@octos.test', self.branch)

    def test_assign_returns_200(self):
        res = self.client.post(self.url_assign(self.convo.pk), {'user_id': self.agent.id})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_assign_sets_assigned_to(self):
        self.client.post(self.url_assign(self.convo.pk), {'user_id': self.agent.id})
        self.convo.refresh_from_db()
        self.assertEqual(self.convo.assigned_to, self.agent)

    def test_assign_logs_system_message(self):
        self.client.post(self.url_assign(self.convo.pk), {'user_id': self.agent.id})
        note = Message.objects.filter(
            conversation=self.convo, is_internal_note=True
        ).last()
        self.assertIsNotNone(note)
        self.assertIn(self.agent.full_name, note.body)

    def test_assign_returns_agent_name(self):
        res = self.client.post(self.url_assign(self.convo.pk), {'user_id': self.agent.id})
        self.assertIn('assigned_to', res.data)

    def test_assign_404_unknown_user(self):
        res = self.client.post(self.url_assign(self.convo.pk), {'user_id': 99999})
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_assign_400_missing_user_id(self):
        res = self.client.post(self.url_assign(self.convo.pk), {})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reassign_logs_reassignment_note(self):
        self.convo.assigned_to = self.user
        self.convo.save()
        self.client.post(self.url_assign(self.convo.pk), {'user_id': self.agent.id})
        note = Message.objects.filter(
            conversation=self.convo, is_internal_note=True
        ).last()
        self.assertIn('Reassigned', note.body)


# ─────────────────────────────────────────────────────────────
# Resolve
# ─────────────────────────────────────────────────────────────

class ConversationResolveTests(CommunicationsTestBase):

    def test_resolve_returns_200(self):
        res = self.client.post(self.url_resolve(self.convo.pk))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_resolve_sets_status(self):
        self.client.post(self.url_resolve(self.convo.pk))
        self.convo.refresh_from_db()
        self.assertEqual(self.convo.status, Conversation.RESOLVED)

    def test_resolve_logs_system_message(self):
        self.client.post(self.url_resolve(self.convo.pk))
        note = Message.objects.filter(
            conversation=self.convo, is_internal_note=True
        ).last()
        self.assertIsNotNone(note)
        self.assertIn('resolved', note.body.lower())

    def test_resolve_already_resolved_returns_400(self):
        self.convo.status = Conversation.RESOLVED
        self.convo.save()
        res = self.client.post(self.url_resolve(self.convo.pk))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resolve_404_unknown_conversation(self):
        res = self.client.post(self.url_resolve(99999))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


# ─────────────────────────────────────────────────────────────
# Link Job
# ─────────────────────────────────────────────────────────────

class ConversationLinkJobTests(CommunicationsTestBase):

    def setUp(self):
        super().setUp()
        try:
            self.job = make_job(self.branch)
            self.jobs_available = True
        except Exception:
            self.jobs_available = False

    def test_link_job_returns_200(self):
        if not self.jobs_available:
            self.skipTest('Job model not available')
        res = self.client.post(self.url_link_job(self.convo.pk), {'job_id': self.job.id})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_link_job_adds_job_to_conversation(self):
        if not self.jobs_available:
            self.skipTest('Job model not available')
        self.client.post(self.url_link_job(self.convo.pk), {'job_id': self.job.id})
        self.assertIn(self.job, self.convo.jobs.all())

    def test_unlink_job_clears_jobs(self):
        if not self.jobs_available:
            self.skipTest('Job model not available')
        self.convo.jobs.add(self.job)
        res = self.client.post(
            self.url_link_job(self.convo.pk),
            data='{"job_id": null}',
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(self.convo.jobs.count(), 0)

    def test_link_job_404_unknown_job(self):
        res = self.client.post(self.url_link_job(self.convo.pk), {'job_id': 99999})
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_link_job_404_unknown_conversation(self):
        res = self.client.post(self.url_link_job(99999), {'job_id': 1})
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)