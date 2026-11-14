"""
Front-desk jobs go straight to the attendants (14 Nov 2026).

Run: docker compose exec web python manage.py test apps.jobs.tests_front_desk -t .
"""
from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, Role
from apps.communications.tests import make_org
from apps.jobs.models import Job, JobLineItem, JobStep, JobVerification, Service
from apps.jobs.services import front_desk
from apps.jobs.services.front_desk import DeskRefused
from apps.jobs.services.inspection import arrival_queue

OPEN = 'apps.organization.services.hours.is_open'


class Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org()
        cls.branch.is_trading = True
        cls.branch.opening_time, cls.branch.closing_time = time(0, 0), time(23, 59)
        cls.branch.save()
        roles = {name: Role.objects.get_or_create(name=name, defaults={
                     'display_name': name.title(), 'is_constrained': False, 'scope': 'BRANCH'})[0]
                 for name in ('ATTENDANT', 'CASHIER', 'BRANCH_MANAGER', 'FLOW_COORDINATOR')}
        cls.ama = cls.user('FD-ATT-1', roles['ATTENDANT'], 'Ama')
        cls.esi = cls.user('FD-ATT-2', roles['ATTENDANT'], 'Esi')
        cls.cashier = cls.user('FD-CSH-1', roles['CASHIER'], 'Kojo')
        cls.manager = cls.user('FD-BM-1', roles['BRANCH_MANAGER'], 'Yaw')
        cls.copy = Service.objects.create(name='FD A4 B&W Printing', code='FD-PRINT', category=Service.INSTANT)
        cls.bind = Service.objects.create(name='FD A4 Binding', code='FD-BIND', category=Service.INSTANT)
        cls.banner = Service.objects.create(name='FD Flexy Banner', code='FD-FLEXY', category=Service.PRODUCTION)

    @classmethod
    def user(cls, employee_id, role, name):
        u = CustomUser(
            employee_id=employee_id, first_name=name, last_name='Test',
            email=f'{employee_id.lower()}@test.local', employment_status='ACTIVE',
            is_active=True, is_staff=False, is_superuser=False, is_clocked_in=False,
            must_change_password=False, is_business_owner=False, download_pin_set=False,
            branch=cls.branch, role=role,
        )
        u.set_password('test-pass-123')
        u.save()
        return u

    def setUp(self):
        alerts = patch('apps.notifications.services.notify_many')
        self.alerts = alerts.start()
        self.addCleanup(alerts.stop)

    def online_job(self, *services):
        """A paid online order, as convert() leaves it, with one line per service."""
        job = Job.objects.create(
            branch=self.branch, job_type=Job.PRODUCTION, title='Online order', status=Job.PAID,
            payment_state=Job.Payment.SETTLED, intake_channel=Job.ONLINE,
            estimated_cost=Decimal('40.00'), amount_paid=Decimal('40.00'),
            estimated_ready_at=timezone.now() + timedelta(hours=2),
        )
        for position, service in enumerate(services):
            JobLineItem.objects.create(job=job, service=service, quantity=1, pages=10,
                                       unit_price=Decimal('1.00'), line_total=Decimal('10.00'),
                                       position=position)
        front_desk.route(job)
        job.refresh_from_db()
        return job


class RoutingTests(Base):

    def test_all_instant_work_goes_to_the_front_desk(self):
        job = self.online_job(self.copy, self.bind)
        self.assertTrue(job.front_desk)
        self.assertNotIn(job, arrival_queue(self.branch))
        self.assertIn(job, front_desk.queue(self.branch))

    def test_a_mixed_order_goes_to_the_coordinator_whole(self):
        job = self.online_job(self.copy, self.banner)
        self.assertFalse(job.front_desk)
        self.assertIn(job, arrival_queue(self.branch))
        self.assertNotIn(job, front_desk.queue(self.branch))


class TakeTests(Base):

    def test_the_first_to_take_it_owns_it(self):
        job = self.online_job(self.copy)
        front_desk.take(job.pk, self.branch, self.ama)
        front_desk.take(job.pk, self.branch, self.ama)          # again: harmless
        with self.assertRaises(DeskRefused):
            front_desk.take(job.pk, self.branch, self.esi)
        job.refresh_from_db()
        self.assertEqual(job.desk_taken_by, self.ama)

    def test_a_cashier_cannot_take_front_desk_work(self):
        job = self.online_job(self.copy)
        with self.assertRaises(DeskRefused):
            front_desk.take(job.pk, self.branch, self.cashier)


class DoingItTests(Base):

    def taken(self):
        job = self.online_job(self.copy)
        front_desk.take(job.pk, self.branch, self.ama)
        job.refresh_from_db()
        return job

    def test_check_start_done(self):
        job = self.taken()
        front_desk.start(job, self.ama, list(front_desk.DESK_CHECKS))
        job.refresh_from_db()
        self.assertEqual(job.work_state, 'IN_PRODUCTION')
        self.assertTrue(job.is_verified)
        self.assertEqual(job.verifications.get().checked_by, self.ama)
        self.assertFalse(JobStep.objects.filter(job=job).exists())      # no machine steps
        front_desk.finish(job, self.ama)
        job.refresh_from_db()
        self.assertEqual(job.work_state, 'DONE')
        self.assertEqual(job.status, 'READY')

    def test_both_checks_come_before_start(self):
        job = self.taken()
        with self.assertRaises(DeskRefused):
            front_desk.start(job, self.ama, ['file_opened'])

    def test_only_the_attendant_who_took_it_can_do_it(self):
        job = self.taken()
        with self.assertRaises(PermissionError):
            front_desk.start(job, self.esi, list(front_desk.DESK_CHECKS))

    def test_a_problem_holds_it_and_resume_frees_it(self):
        job = self.taken()
        outcome = next(v for v, _ in JobVerification.Outcome.choices if v != JobVerification.Outcome.PASSED)
        front_desk.hold(job, self.ama, outcome, 'The PDF is password protected')
        from apps.jobs.status_engine import JobStatusEngine
        self.assertTrue(JobStatusEngine(job).is_halted())
        front_desk.resume(job, self.ama)
        self.assertFalse(JobStatusEngine(job).is_halted())


class EscalationTests(Base):

    def waited(self, minutes):
        job = self.online_job(self.copy)
        Job.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(minutes=minutes))
        return job

    def test_the_bm_is_told_once_after_ten_minutes(self):
        self.waited(11)
        with patch(OPEN, return_value=True):
            self.assertEqual(front_desk.escalate(), 1)
            self.assertEqual(front_desk.escalate(), 0)
        self.assertIn(self.manager, list(self.alerts.call_args[0][0]))

    def test_not_before_ten_minutes(self):
        self.waited(6)
        with patch(OPEN, return_value=True):
            self.assertEqual(front_desk.escalate(), 0)

    def test_taken_work_is_not_escalated(self):
        job = self.waited(30)
        front_desk.take(job.pk, self.branch, self.ama)
        with patch(OPEN, return_value=True):
            self.assertEqual(front_desk.escalate(), 0)

    def test_nobody_is_told_while_the_branch_is_closed(self):
        self.waited(30)
        with patch(OPEN, return_value=False):
            self.assertEqual(front_desk.escalate(), 0)


class ApiTests(Base):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.ama)

    def test_the_work_tab_takes_checks_and_finishes(self):
        job = self.online_job(self.copy)
        queue = self.client.get('/api/v1/jobs/desk/queue/').json()
        self.assertEqual([j['id'] for j in queue['jobs']], [job.pk])
        self.assertEqual(queue['checks'], list(front_desk.DESK_CHECKS))

        self.assertEqual(self.client.post(f'/api/v1/jobs/{job.pk}/desk/take/').status_code, 200)
        started = self.client.post(f'/api/v1/jobs/{job.pk}/desk/start/',
                                   {'signed_checks': list(front_desk.DESK_CHECKS)}, format='json')
        self.assertEqual(started.status_code, 200, started.content)
        done = self.client.post(f'/api/v1/jobs/{job.pk}/desk/done/')
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual(self.client.get('/api/v1/jobs/desk/queue/').json()['jobs'], [])

    def test_someone_elses_job_is_refused(self):
        job = self.online_job(self.copy)
        front_desk.take(job.pk, self.branch, self.esi)
        self.assertEqual(self.client.post(f'/api/v1/jobs/{job.pk}/desk/take/').status_code, 409)
