"""
The assistant's tools: facts from the floor, nothing invented.
Fixed dates: Sun 8, Mon 9 November 2026.
"""
from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.communications.assistant import tools
from apps.communications.tests import make_job, make_org
from apps.customers.models.customer import CustomerProfile
from apps.jobs.models import Job

SUN, MON = date(2026, 11, 8), date(2026, 11, 9)


def at(day, hh, mm=0):
    return timezone.make_aware(datetime(day.year, day.month, day.day, hh, mm))


class BranchHoursTests(TestCase):

    def setUp(self):
        self.branch = make_org()  # 08:00 to 19:30

    def test_open_on_a_weekday(self):
        facts = tools.branch_hours(self.branch, at(MON, 10))
        self.assertTrue(facts['open_now'])
        self.assertEqual(facts['today'], {'opens': '8:00am', 'closes': '7:30pm'})
        self.assertEqual(facts['next_opening'], '8:00am tomorrow')

    def test_closed_on_sunday_says_why_and_when(self):
        facts = tools.branch_hours(self.branch, at(SUN, 11))
        self.assertFalse(facts['open_now'])
        self.assertEqual(facts['today'], {'closed': 'Sunday'})
        self.assertEqual(facts['next_opening'], '8:00am tomorrow')


class CustomerJobsTests(TestCase):

    def setUp(self):
        self.branch = make_org()
        self.ama = CustomerProfile.objects.create(
            first_name='Ama', last_name='Mensah', phone='+233244123456', customer_type='INDIVIDUAL',
        )

    def job(self, **fields):
        job = make_job(self.branch)
        defaults = dict(
            customer=self.ama, title='Banners',
            work_state=Job.Work.IN_PRODUCTION, handover_state='',
            estimated_cost=Decimal('50.00'), amount_paid=Decimal('20.00'),
        )
        defaults.update(fields)
        for name, value in defaults.items():
            setattr(job, name, value)
        job.save()
        return job

    def test_an_open_job_in_plain_words_with_the_cashiers_balance(self):
        job = self.job()
        facts = tools.customer_jobs('+233244123456', at(MON, 10))
        self.assertTrue(facts['found'])
        (found,) = facts['jobs']
        self.assertEqual(found['stage'], 'being made now')
        self.assertEqual(found['balance_due'], 'GHS 30.00')
        self.assertEqual(found['balance_due'], f'GHS {job.balance_due:.2f}')  # the cashier's figure
        self.assertFalse(found['paid_in_full'])
        self.assertTrue(found['ref'].isdigit())

    def test_found_by_the_number_as_ghanaians_type_it(self):
        self.job()
        self.assertTrue(tools.customer_jobs('0244123456', at(MON, 10))['found'])

    def test_ready_to_collect(self):
        self.job(work_state=Job.Work.DONE, handover_state=Job.Handover.AWAITING_COLLECTION)
        (found,) = tools.customer_jobs('+233244123456', at(MON, 10))['jobs']
        self.assertTrue(found['ready_to_collect'])
        self.assertEqual(found['stage'], 'finished')

    def test_handed_over_drafts_and_voided_jobs_are_not_open(self):
        self.job(handover_state=Job.Handover.HANDED_OVER)
        self.job(status=Job.DRAFT)
        self.job(voided_at=timezone.now())
        self.assertEqual(tools.customer_jobs('+233244123456', at(MON, 10)), {'found': False, 'jobs': []})

    def test_someone_elses_jobs_are_never_shown(self):
        other = CustomerProfile.objects.create(
            first_name='Kofi', last_name='Boateng', phone='+233200000999', customer_type='INDIVIDUAL',
        )
        self.job(customer=other)
        self.assertFalse(tools.customer_jobs('+233244123456', at(MON, 10))['found'])

    def test_a_number_that_isnt_real_finds_nothing(self):
        self.assertEqual(tools.customer_jobs('12345'), {'found': False, 'jobs': []})