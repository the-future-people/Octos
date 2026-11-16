"""
The attendant's Today screen (16 Nov 2026): one call with their day, what
needs them, the team, their jobs and who just scanned in.

Nothing here depends on the day of the week: past days are made relative
to now, and the streak only counts days the branch actually recorded work.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, Role
from apps.communications.models import Conversation
from apps.communications.tests import make_org
from apps.jobs.models import Job
from apps.jobs.selectors.attendant_today import attendant_today
from apps.spine import kinds
from apps.spine.models import Event


class Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org('-AT')
        role = Role.objects.get_or_create(name='ATTENDANT', defaults={
            'display_name': 'Attendant', 'is_constrained': False, 'scope': 'BRANCH'})[0]
        cls.kofi = cls.user('AT-1', 'Kofi', role)
        cls.abena = cls.user('AT-2', 'Abena', role)

    @classmethod
    def user(cls, employee_id, name, role):
        u = CustomUser(employee_id=employee_id, first_name=name, last_name='Test',
                       email=f'{employee_id.lower()}@test.local', employment_status='ACTIVE',
                       is_active=True, branch=cls.branch, role=role)
        u.set_password('test-pass-123')
        u.save()
        return u

    def job(self, by=None, status=Job.PAID, cost='20.00', days_ago=0, **extra):
        job = Job.objects.create(branch=self.branch, job_type=Job.INSTANT, title='Photocopy', status=status,
                                 estimated_cost=Decimal(cost), intake_by=by, **extra)
        if days_ago:
            Job.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        return job

    def today(self, user=None):
        return attendant_today(user or self.kofi)


class MyDayTests(Base):

    def test_my_jobs_today_paid_and_value(self):
        self.job(self.kofi)
        self.job(self.kofi, status=Job.PENDING_PAYMENT, cost='6.00')
        self.job(self.kofi, status=Job.DRAFT)          # not recorded yet
        self.job(self.abena)                           # someone else's
        self.job(self.kofi, days_ago=1)                # yesterday
        me = self.today()['me']
        self.assertEqual((me['total'], me['paid'], me['value']), (2, 1, 26.0))

    def test_a_streak_counts_days_at_target_and_skips_closed_days(self):
        for days_ago in (1, 3):                        # day 2 the branch was closed
            for _ in range(10):
                self.job(self.kofi, days_ago=days_ago)
        self.assertEqual(self.today()['me']['streak'], 2)

    def test_a_missed_day_ends_the_streak(self):
        for _ in range(10):
            self.job(self.kofi, days_ago=1)
        self.job(self.kofi, days_ago=2)                # recorded, below target
        for _ in range(10):
            self.job(self.kofi, days_ago=3)
        self.assertEqual(self.today()['me']['streak'], 1)


class NeedsTests(Base):

    def test_front_desk_work_nobody_has_taken(self):
        self.job(None, front_desk=True)
        self.job(None, front_desk=True, desk_taken_by=self.abena, desk_taken_at=timezone.now())
        desk = self.today()['needs']['desk']
        self.assertEqual(desk['count'], 1)
        self.assertEqual(desk['first']['what'], 'Photocopy')

    def test_chats_handed_to_a_person(self):
        Conversation.objects.create(branch=self.branch, channel='WHATSAPP', contact_phone='+233240000001',
                                    contact_name='Kwabena', handled_by=Conversation.STAFF,
                                    handoff_reason='price question', handled_since=timezone.now())
        Conversation.objects.create(branch=self.branch, channel='WHATSAPP', contact_phone='+233240000002',
                                    handled_by=Conversation.OCTOS)
        chats = self.today()['needs']['chats']
        self.assertEqual((chats['count'], chats['first_name']), (1, 'Kwabena'))

    def test_only_my_own_drafts(self):
        self.job(self.kofi, status=Job.DRAFT, draft_expires_at=timezone.now() + timedelta(hours=2))
        self.job(self.abena, status=Job.DRAFT, draft_expires_at=timezone.now() + timedelta(hours=2))
        self.job(self.kofi, status=Job.DRAFT, draft_expires_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(self.today()['needs']['drafts']['count'], 1)

    def test_nothing_waiting(self):
        needs = self.today()['needs']
        self.assertEqual([needs[k]['count'] for k in ('desk', 'pickups', 'chats', 'drafts')], [0, 0, 0, 0])


class TeamAndJobsTests(Base):

    def test_team_today_against_a_usual_day(self):
        self.job(self.kofi)
        self.job(self.abena)
        self.job(self.abena)
        for _ in range(4):
            self.job(self.abena, days_ago=1)
        for _ in range(6):
            self.job(self.abena, days_ago=2)
        team = self.today()['team']
        self.assertEqual((team['total'], team['mine'], team['usual']), (3, 1, 5))
        self.assertIsNotNone(team['busiest_hour'])

    def test_my_jobs_newest_first_with_paid_state(self):
        first = self.job(self.kofi, status=Job.PENDING_PAYMENT)
        second = self.job(self.kofi)
        Job.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(minutes=30))
        jobs = self.today()['jobs']
        self.assertEqual([(j['id'], j['paid']) for j in jobs], [(second.pk, True), (first.pk, False)])
        self.assertEqual(jobs[0]['who'], 'Walk-in')


class ScansTests(Base):

    def scan(self, minutes_ago, phone):
        chat = Conversation.objects.create(branch=self.branch, channel='WHATSAPP', contact_phone=phone,
                                           contact_name='Abena Asante')
        Event.objects.create(kind=kinds.PRESENCE_COUNTER, branch=self.branch, conversation=chat,
                             occurred_at=timezone.now() - timedelta(minutes=minutes_ago),
                             payload={'verified': True})
        return chat

    def test_who_scanned_in_the_last_ten_minutes(self):
        chat = self.scan(2, '+233240000010')
        self.scan(25, '+233240000011')
        scans = self.today()['scans']
        self.assertEqual([(s['conversation_id'], s['name'], s['verified']) for s in scans],
                         [(chat.pk, 'Abena Asante', True)])


class EndpointTests(Base):

    def test_one_call_for_the_screen(self):
        api = APIClient()
        api.force_authenticate(self.kofi)
        response = api.get('/api/v1/jobs/attendant/today/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {'me', 'needs', 'team', 'jobs', 'shift', 'scans'})
