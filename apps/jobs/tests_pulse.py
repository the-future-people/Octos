"""
The branch's pulse (15 Nov 2026): floor load, machines up, promises kept.

Times are pinned to a Monday in Accra, never read from the calendar, so the
suite passes on any day of the week.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, Role
from apps.communications.tests import make_org
from apps.jobs.models import Job, JobLineItem, JobStatusLog, JobStep, Service
from apps.jobs.selectors.branch_pulse import branch_pulse
from apps.production.models import Machine, MachineType, Station

ACCRA = ZoneInfo('Africa/Accra')
MONDAY_2PM = datetime(2026, 11, 16, 14, 0, tzinfo=ACCRA)


class Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_org('-PL')
        cls.branch.opening_time, cls.branch.closing_time = time(8, 0), time(18, 0)
        cls.branch.save()
        role = Role.objects.get_or_create(name='BRANCH_MANAGER', defaults={
            'display_name': 'Branch Manager', 'is_constrained': False, 'scope': 'BRANCH'})[0]
        cls.manager = CustomUser(
            employee_id='PL-BM', first_name='Yaw', last_name='Test', email='pl-bm@test.local',
            employment_status='ACTIVE', is_active=True, branch=cls.branch, role=role,
        )
        cls.manager.set_password('test-pass-123')
        cls.manager.save()
        cls.station = Station.objects.create(code='PL-PRINT', name='Printing', sequence=1)
        kind = MachineType.objects.create(code='PL-LARGE', name='Large format', station=cls.station)
        cls.six = Machine.objects.create(branch=cls.branch, machine_type=kind, name='6ft')
        cls.ten = Machine.objects.create(branch=cls.branch, machine_type=kind, name='10ft')
        cls.banner = Service.objects.create(name='PL Flexy Banner', code='PL-FLEXY', category=Service.PRODUCTION)

    def job(self, status=Job.PAID, promise_state=''):
        job = Job.objects.create(branch=self.branch, job_type=Job.PRODUCTION, title='Banner',
                                 status=status, estimated_cost=Decimal('40.00'), promise_state=promise_state)
        line = JobLineItem.objects.create(job=job, service=self.banner, quantity=1, unit_price=Decimal('40.00'),
                                          line_total=Decimal('40.00'), position=0)
        return job, line

    def step(self, minutes, state=JobStep.State.WAITING, by_hand=False, status=Job.PAID, sequence=1):
        job, line = self.job(status=status)
        return JobStep.objects.create(job=job, line_item=line, station=self.station, sequence=sequence,
                                      machine=None if by_hand else self.six, by_hand=by_hand,
                                      state=state, expected_minutes=Decimal(minutes))

    def ready(self, promise_state, days_ago):
        job, _ = self.job(promise_state=promise_state)
        JobStatusLog.objects.create(job=job, axis=JobStatusLog.Axis.WORK, from_status='IN_PRODUCTION',
                                    to_status='DONE', actor=self.manager,
                                    transitioned_at=MONDAY_2PM - timedelta(days=days_ago))
        return job


class FloorLoadTests(Base):

    def test_waiting_work_against_the_time_the_machines_have_left(self):
        # 2pm to 6pm is 240 minutes, on two machines: 480. 240 waiting is half.
        self.step(180)
        self.step(60, state=JobStep.State.ACTIVE)
        floor = branch_pulse(self.branch, now=MONDAY_2PM)['floor']
        self.assertEqual(floor, {'state': 'open', 'percent': 50, 'queued_minutes': 240})

    def test_done_steps_handwork_and_cancelled_jobs_are_not_waiting(self):
        self.step(120)
        self.step(500, state=JobStep.State.DONE)
        self.step(500, by_hand=True)
        self.step(500, status='CANCELLED')
        self.assertEqual(branch_pulse(self.branch, now=MONDAY_2PM)['floor']['queued_minutes'], 120)

    def test_more_work_than_time_goes_over_a_hundred(self):
        self.step(600)
        self.assertEqual(branch_pulse(self.branch, now=MONDAY_2PM)['floor']['percent'], 125)

    def test_a_machine_down_leaves_less_time(self):
        self.ten.is_available = False
        self.ten.save()
        self.step(120)
        self.assertEqual(branch_pulse(self.branch, now=MONDAY_2PM)['floor']['percent'], 50)

    def test_before_opening_the_whole_day_counts(self):
        self.step(600)   # 8am to 6pm on two machines: 1200 minutes
        early = MONDAY_2PM.replace(hour=7)
        self.assertEqual(branch_pulse(self.branch, now=early)['floor']['percent'], 50)

    def test_after_closing_it_shows_what_is_queued_for_the_morning(self):
        self.step(200)
        late = MONDAY_2PM.replace(hour=19)
        self.assertEqual(branch_pulse(self.branch, now=late)['floor'],
                         {'state': 'closed', 'percent': None, 'queued_minutes': 200})

    def test_closed_all_sunday(self):
        sunday = MONDAY_2PM - timedelta(days=1)
        self.assertEqual(branch_pulse(self.branch, now=sunday)['floor']['state'], 'closed')

    def test_no_machine_up_gives_no_percentage(self):
        Machine.objects.filter(branch=self.branch).update(is_available=False)
        self.step(60)
        self.assertIsNone(branch_pulse(self.branch, now=MONDAY_2PM)['floor']['percent'])


class MachinesTests(Base):

    def test_up_of_total_and_why_any_are_down(self):
        self.ten.is_available, self.ten.unavailable_reason = False, 'Head clogged'
        self.ten.save()
        sold = Machine.objects.create(branch=self.branch, machine_type=self.six.machine_type, name='Old 4ft',
                                      is_active=False)
        machines = branch_pulse(self.branch, now=MONDAY_2PM)['machines']
        self.assertEqual(machines, {'up': 1, 'total': 2, 'down': [{'name': '10ft', 'reason': 'Head clogged'}]})
        self.assertTrue(sold.pk)


class PromisesTests(Base):

    def test_kept_of_scored_jobs_ready_in_the_last_seven_days(self):
        self.ready('KEPT', days_ago=1)
        self.ready('KEPT', days_ago=6)
        self.ready('BROKEN', days_ago=2)
        self.ready('KEPT', days_ago=8)     # too long ago
        self.ready('', days_ago=1)         # never promised: not scored
        promises = branch_pulse(self.branch, now=MONDAY_2PM)['promises']
        self.assertEqual(promises, {'kept': 2, 'total': 3, 'days': 7, 'percent': 67})

    def test_nothing_ready_yet(self):
        self.assertIsNone(branch_pulse(self.branch, now=MONDAY_2PM)['promises']['percent'])


class EndpointTests(Base):

    def test_the_pulse_for_the_users_branch(self):
        api = APIClient()
        api.force_authenticate(self.manager)
        response = api.get('/api/v1/jobs/pulse/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {'floor', 'machines', 'promises'})
        self.assertEqual(response.data['machines']['total'], 2)
