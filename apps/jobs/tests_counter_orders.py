"""
Pays at the counter (24 Nov 2026): Octos takes the order, the customer pays
when they collect.

Run: docker compose run --rm web python manage.py test apps.jobs.tests_counter_orders -t .
"""
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.communications.assistant import checker, counter, ordering
from apps.communications.models import Conversation
from apps.communications.tests import make_conversation
from apps.customers.models import CustomerProfile
from apps.finance.models import DailySalesSheet
from apps.jobs.models import Job, JobFile, Service
from apps.jobs.services import counter_orders, front_desk
from apps.jobs.services.counter_orders import CounterRefused
from apps.jobs.tests_front_desk import Base
from apps.storefront.models import Lead, OnlineOrder

PHONE = '+233244000731'


def at(day, hour, minute=0):
    return timezone.make_aware(datetime(2026, 11, day, hour, minute))


class CounterBase(Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        octos_role = Role.objects.get_or_create(name='OCTOS', defaults={
            'display_name': 'Octos', 'is_constrained': False, 'scope': 'BRANCH'})[0]
        cls.octos = cls.user('OCTOS-1', octos_role, 'Octos')
        Service.objects.filter(pk__in=[cls.copy.pk, cls.bind.pk]).update(category=Service.INSTANT)

    def setUp(self):
        super().setUp()
        self.chat = make_conversation(None, contact_phone=PHONE, contact_name='Ama')
        self.lead = Lead.objects.create(phone=PHONE, first_name='Ama')
        sheet = DailySalesSheet.objects.create(branch=self.branch, date=timezone.localdate(),
                                               status=DailySalesSheet.Status.OPEN)
        opened = patch('apps.finance.sheet_engine.SheetEngine.get_or_open_today', return_value=(sheet, False))
        opened.start()
        self.addCleanup(opened.stop)
        self.sheet = sheet

    def order(self, *lines, total='12.00'):
        lines = lines or ((self.copy, '10.00', [(self.bind, '2.00')]),)
        items = [{
            'service': service.pk, 'service_name': service.name, 'quantity': 1,
            'specifications': {'pages': 4}, 'unit_price': price, 'base_total': price,
            'total': str(Decimal(price) + sum(Decimal(p) for _, p in addons)),
            'addons': [{'service': a.pk, 'quantity': 1, 'unit_price': p, 'total': p} for a, p in addons],
        } for service, price, addons in lines]
        return OnlineOrder.objects.create(
            lead=self.lead, branch=self.branch, status=OnlineOrder.Status.AWAITING_PAYMENT,
            line_items=items, total=Decimal(total), promised_for=timezone.now() + timedelta(minutes=40),
            notes=f'Taken by Octos on WhatsApp (conversation {self.chat.pk}).')

    def known(self):
        return CustomerProfile.objects.create(first_name='Ama', phone=PHONE, customer_type='INDIVIDUAL')


class CodeTests(CounterBase):

    def test_four_digits_and_never_twice(self):
        code = counter_orders.new_code()
        self.assertRegex(code, r'^\d{4}$')
        Job.objects.create(branch=self.branch, job_type=Job.INSTANT, title='x', counter_code=code)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Job.objects.create(branch=self.branch, job_type=Job.INSTANT, title='y', counter_code=code)

    def test_five_digits_once_four_are_taken(self):
        with patch.object(Job.objects, 'filter') as taken:
            taken.return_value.exists.side_effect = [True] * 40 + [False]
            self.assertRegex(counter_orders.new_code(), r'^\d{5}$')


class ReserveTests(CounterBase):

    def test_a_known_customer_s_small_order_is_printed_ahead(self):
        self.known()
        job = counter_orders.reserve(self.order(), self.chat)
        self.assertEqual((job.status, job.job_type, job.front_desk, job.print_ahead),
                         (Job.AWAITING_ARRIVAL, Job.INSTANT, True, True))
        self.assertEqual(job.payment_state, Job.Payment.UNPAID)
        self.assertEqual(job.estimated_cost, Decimal('12.00'))
        self.assertEqual(job.line_items.count(), 2)
        self.assertIsNotNone(job.estimated_ready_at)
        self.assertIn(job, self.chat.jobs.all())
        self.assertEqual(OnlineOrder.objects.get(lead=self.lead).status, OnlineOrder.Status.COUNTER)
        self.assertIn(job, front_desk.queue(self.branch))

    def test_a_stranger_s_order_is_printed_when_they_arrive(self):
        job = counter_orders.reserve(self.order(), self.chat)
        self.assertFalse(job.print_ahead)
        self.assertIsNone(job.estimated_ready_at)
        self.assertIn(job, front_desk.queue(self.branch))

    def test_a_chat_a_month_old_counts_as_known(self):
        Conversation.objects.filter(pk=self.chat.pk).update(created_at=timezone.now() - timedelta(days=31))
        self.chat.refresh_from_db()
        self.assertTrue(counter_orders.reserve(self.order(), self.chat).print_ahead)

    def test_over_fifty_cedis_waits_for_them(self):
        self.known()
        job = counter_orders.reserve(self.order((self.copy, '51.00', []), total='51.00'), self.chat)
        self.assertFalse(job.print_ahead)

    def test_a_no_show_loses_printing_ahead(self):
        ama = self.known()
        Job.objects.create(branch=self.branch, job_type=Job.INSTANT, title='old', customer=ama,
                           status=Job.CANCELLED, no_show=True)
        self.assertFalse(counter_orders.reserve(self.order(), self.chat).print_ahead)

    def test_production_work_needs_its_deposit_and_nothing_is_made(self):
        order = self.order((self.banner, '40.00', []), total='40.00')
        with self.assertRaisesMessage(CounterRefused, 'needs_deposit'):
            counter_orders.reserve(order, self.chat)
        self.assertFalse(Job.objects.filter(counter_code__isnull=False).exists())
        order.refresh_from_db()
        self.assertEqual(order.status, OnlineOrder.Status.AWAITING_PAYMENT)

    def test_asking_twice_gives_the_same_job_and_code(self):
        order = self.order()
        first = counter_orders.reserve(order, self.chat)
        order.refresh_from_db()
        self.assertEqual(counter_orders.reserve(order, self.chat).pk, first.pk)
        self.assertEqual(Job.objects.filter(counter_code__isnull=False).count(), 1)

    def test_a_paid_order_is_refused(self):
        order = self.order()
        OnlineOrder.objects.filter(pk=order.pk).update(status=OnlineOrder.Status.PAID)
        order.refresh_from_db()
        with self.assertRaises(CounterRefused):
            counter_orders.reserve(order, self.chat)


class CounterFlowTests(CounterBase):

    def test_they_come_and_it_goes_to_the_cashier_as_a_counter_sale(self):
        job = counter_orders.reserve(self.order(), self.chat)
        counter_orders.here(job)
        self.assertIsNotNone(Job.objects.get(pk=job.pk).arrived_at)
        counter_orders.send_to_cashier(job, self.esi)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.PENDING_PAYMENT)
        self.assertEqual(job.daily_sheet, self.sheet)
        self.assertNotIn(job, front_desk.queue(self.branch))

    def test_only_an_attendant_sends_it(self):
        job = counter_orders.reserve(self.order(), self.chat)
        with self.assertRaises(PermissionError):
            counter_orders.send_to_cashier(job, self.cashier)

    def test_printed_ahead_it_stays_on_work_until_they_come_and_they_are_told(self):
        self.known()
        job = counter_orders.reserve(self.order(), self.chat)
        front_desk.take(job.pk, self.branch, self.ama)
        job.refresh_from_db()
        front_desk.start(job, self.ama, list(front_desk.DESK_CHECKS))
        job.refresh_from_db()
        with patch('apps.jobs.services.counter_orders.tell_ready') as told, self.captureOnCommitCallbacks(execute=True):
            front_desk.finish(job, self.ama)
        told.assert_called_once()
        job.refresh_from_db()
        self.assertEqual((job.work_state, job.status), ('DONE', Job.AWAITING_ARRIVAL))
        self.assertIn(job, front_desk.queue(self.branch))

    def test_the_ready_message_has_the_code(self):
        self.known()
        job = counter_orders.reserve(self.order(), self.chat)
        text = counter_orders.ready_text(job)
        self.assertIn(job.counter_code, text)
        self.assertIn('Pay when you collect', text)

    def test_print_on_arrival_is_not_escalated_before_they_come(self):
        job = counter_orders.reserve(self.order(), self.chat)
        Job.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(hours=1))
        with patch('apps.organization.services.hours.is_open', return_value=True):
            self.assertEqual(front_desk.escalate(), 0)
            counter_orders.here(Job.objects.get(pk=job.pk))
            self.assertEqual(front_desk.escalate(), 0)          # the clock starts when they arrive
            Job.objects.filter(pk=job.pk).update(arrived_at=timezone.now() - timedelta(minutes=11))
            self.assertEqual(front_desk.escalate(), 1)

    def test_the_counter_qr_marks_them_here_and_says_the_code(self):
        job = counter_orders.reserve(self.order(), self.chat)
        said = counter._order_waiting(self.chat, self.branch, timezone.now())
        self.assertIn(job.counter_code, said)
        self.assertIsNotNone(Job.objects.get(pk=job.pk).arrived_at)
        self.assertEqual(counter._order_waiting(make_conversation(None, contact_phone='+233244000999'),
                                                self.branch, timezone.now()), '')


class ShelfTests(CounterBase):

    def setUp(self):
        super().setUp()
        self.branch.opening_time, self.branch.closing_time = time(8, 0), time(18, 0)
        self.branch.save()

    def made_at(self, when):
        job = counter_orders.reserve(self.order(), self.chat)
        Job.objects.filter(pk=job.pk).update(created_at=when)
        return Job.objects.get(pk=job.pk)

    def test_not_collected_by_closing_it_goes_on_the_shelf(self):
        job = self.made_at(at(11, 10))                                  # a Wednesday
        self.assertEqual(counter_orders.tidy(at(11, 17, 55)), (0, 0))
        self.assertEqual(counter_orders.tidy(at(11, 18, 5)), (1, 0))
        job.refresh_from_db()
        self.assertIsNotNone(job.shelved_at)
        self.assertNotIn(job, front_desk.queue(self.branch))
        self.assertEqual(counter_orders.shelf(self.branch, job.counter_code), [job])

    def test_an_order_after_closing_waits_for_the_next_day_s_close(self):
        self.made_at(at(11, 21))
        self.assertEqual(counter_orders.tidy(at(12, 9)), (0, 0))
        self.assertEqual(counter_orders.tidy(at(12, 18, 5)), (1, 0))

    def test_a_week_on_the_shelf_and_octos_cancels_it(self):
        job = self.made_at(at(11, 10))
        JobFile.objects.create(job=job, file=ContentFile(b'%PDF-1.4', name='exam.pdf'), original_filename='exam.pdf')
        Job.objects.filter(pk=job.pk).update(shelved_at=at(11, 18, 5))
        self.assertEqual(counter_orders.tidy(at(18, 18, 0)), (0, 0))
        self.assertEqual(counter_orders.tidy(at(18, 18, 10)), (0, 1))
        job.refresh_from_db()
        self.assertEqual((job.status, job.no_show), (Job.CANCELLED, True))
        self.assertFalse(JobFile.objects.filter(job=job).exists())
        from apps.jobs.models import JobStatusLog
        log = JobStatusLog.objects.filter(job=job, to_status=Job.CANCELLED).get()
        self.assertEqual(log.actor, self.octos)

    def test_found_on_the_shelf_they_come_back_to_work(self):
        job = self.made_at(at(11, 10))
        Job.objects.filter(pk=job.pk).update(shelved_at=at(11, 18, 5))
        counter_orders.here(Job.objects.get(pk=job.pk))
        job.refresh_from_db()
        self.assertIsNone(job.shelved_at)
        self.assertIn(job, front_desk.queue(self.branch))


class DeskApiTests(CounterBase):

    def test_the_work_list_shows_the_counter_details_and_sends_it_to_the_cashier(self):
        job = counter_orders.reserve(self.order(), self.chat)
        api = APIClient()
        api.force_authenticate(self.esi)
        row = next(r for r in api.get('/api/v1/jobs/desk/queue/').json()['jobs'] if r['id'] == job.pk)
        self.assertEqual(row['counter']['code'], job.counter_code)
        self.assertFalse(row['counter']['print_ahead'])
        self.assertEqual(row['source'], 'WhatsApp order, pays at the counter')
        response = api.post(f'/api/v1/jobs/{job.pk}/desk/cashier/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Job.objects.get(pk=job.pk).status, Job.PENDING_PAYMENT)

    def test_the_shelf_finds_by_code(self):
        job = counter_orders.reserve(self.order(), self.chat)
        Job.objects.filter(pk=job.pk).update(shelved_at=timezone.now())
        api = APIClient()
        api.force_authenticate(self.ama)
        found = api.get('/api/v1/jobs/desk/shelf/', {'q': job.counter_code}).json()['jobs']
        self.assertEqual([r['id'] for r in found], [job.pk])
        self.assertIn('cancels_on', found[0])
        self.assertEqual(api.post(f'/api/v1/jobs/{job.pk}/desk/here/').status_code, 200)


class OctosToolTests(CounterBase):

    def test_octos_gets_the_code_and_what_to_say(self):
        self.known()
        order = self.order()
        result = ordering.pay_at_counter(self.chat, order.order_number)
        self.assertTrue(result['success'])
        self.assertTrue(result['printed_ahead'])
        self.assertRegex(result['code'], r'^\d{4}$')
        self.assertEqual(result['total'], 'GHS 12.00')
        self.assertIn("Don't offer the link again", result['say'])

    def test_production_work_tells_octos_about_the_deposit(self):
        order = self.order((self.banner, '40.00', []), total='40.00')
        result = ordering.pay_at_counter(self.chat, order.order_number)
        self.assertTrue(result['needs_deposit'])
        self.assertIn('70%', result['say'])

    def test_a_wrong_code_in_a_reply_is_caught(self):
        self.assertEqual(checker.unverified('Your code is 4821.', '{"code": "4821"}'), [])
        self.assertEqual(checker.unverified('Your code is 4812.', '{"code": "4821"}'), ['code 4812'])
