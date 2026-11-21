"""
Money owed, one way everywhere (21 Nov 2026).

Mr. Dwumfour: work printed and delivered on a proforma, never paid, and the
proforma quietly expired, so what he owed was nowhere. Now:

  record_owed   an expired proforma whose work was done becomes a job, done
                and handed over, owing its whole value
  owing.py      one rule for what owes us, used by Balances, who owes, the
                money lens and the statement
  statement     what they owe from before, their new work, the total
  renew         an expired proforma whose work was never done, at today's prices
  paying        he points at a job; its balance is taken like any other
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.customers.models import CustomerProfile
from apps.finance.services import owing
from apps.finance.services.statement_pdf import build_statement_pdf
from apps.jobs.models import Job, PricingRule, ProformaInvoice, Service
from apps.jobs.services.proforma_engine import ProformaEngine
from apps.jobs.tests import JobsFixtureMixin


class Base(JobsFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.dwumfour = CustomerProfile.objects.create(
            phone='0555000777', customer_type=CustomerProfile.INDIVIDUAL, first_name='Kwabena',
            last_name='Dwumfour', visit_count=0, total_spend=Decimal('0'), tier=CustomerProfile.REGULAR,
            confidence_score=0, is_priority=False, is_walkin=False, affiliation_active=True)
        PricingRule.objects.create(service=cls.service, branch=cls.branch, base_price=Decimal('10.00'),
                                   color_multiplier=Decimal('1.00'), is_active=True)

    def expired(self, quantity=30):
        engine = ProformaEngine(self.branch)
        p = engine.create(customer=self.dwumfour, raw_lines=[{'service': self.service.pk, 'quantity': quantity,
                                                               'pages': 1}], actor=self.bm)
        engine.issue(p, actor=self.bm)
        ProformaInvoice.objects.filter(pk=p.pk).update(valid_until=timezone.localdate() - timedelta(days=5))
        ProformaEngine.expire_stale_proformas()
        p.refresh_from_db()
        return p

    def new_job(self, cost='40.00'):
        return Job.objects.create(branch=self.branch, job_type=Job.INSTANT, title='Flyers', customer=self.dwumfour,
                                  status=Job.PENDING_PAYMENT, estimated_cost=Decimal(cost), intake_by=self.bm)


class RecordOwedTests(Base):

    def test_the_expired_invoice_becomes_a_delivered_job_owing_its_whole_value(self):
        p = self.expired()
        self.assertEqual(p.status, ProformaInvoice.Status.EXPIRED)
        job = ProformaEngine(self.branch).record_owed(p, self.bm, delivered_on=timezone.localdate() - timedelta(days=30))
        p.refresh_from_db()
        self.assertEqual(p.status, ProformaInvoice.Status.CONVERTED)
        self.assertEqual(p.job, job)
        self.assertEqual(job.estimated_cost, p.total)                  # the price he was served at
        self.assertEqual((job.status, job.payment_state, job.work_state, job.handover_state),
                         (Job.COMPLETE, 'UNPAID', 'DONE', 'HANDED_OVER'))
        self.assertEqual(job.balance_due, p.total)
        self.assertIsNone(job.daily_sheet)                              # not today's work, not today's sales
        self.assertEqual(job.line_items.count(), 1)
        self.assertIn('delivered and never paid', job.notes)

    def test_only_an_expired_proforma(self):
        engine = ProformaEngine(self.branch)
        p = engine.create(customer=self.dwumfour, raw_lines=[{'service': self.service.pk, 'quantity': 1, 'pages': 1}],
                          actor=self.bm)
        engine.issue(p, actor=self.bm)
        with self.assertRaisesMessage(ValueError, 'only an expired proforma'):
            engine.record_owed(p, self.bm)

    def test_never_twice_and_never_by_the_cashier(self):
        p = self.expired()
        with self.assertRaises(PermissionError):
            ProformaEngine(self.branch).record_owed(p, self.cashier)
        ProformaEngine(self.branch).record_owed(p, self.bm)
        p.refresh_from_db()
        with self.assertRaises(ValueError):
            ProformaEngine(self.branch).record_owed(p, self.bm)

    def test_not_delivered_in_the_future(self):
        with self.assertRaisesMessage(ValueError, 'cannot be in the future'):
            ProformaEngine(self.branch).record_owed(self.expired(), self.bm,
                                                    delivered_on=timezone.localdate() + timedelta(days=1))

    def test_the_bm_does_it_from_the_proformas_page(self):
        p = self.expired()
        api = APIClient()
        api.force_authenticate(self.bm)
        r = api.post(f'/api/v1/jobs/proformas/{p.pk}/record-owed/', {'delivered_on': '2026-10-20'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIn('owes GHS 300.00', r.data['detail'])


class OwingTests(Base):

    def test_one_rule_everywhere(self):
        job = ProformaEngine(self.branch).record_owed(self.expired(), self.bm)
        deposit = self.new_job('100.00')
        Job.objects.filter(pk=deposit.pk).update(payment_state='DEPOSIT_PAID', amount_paid=Decimal('70.00'),
                                                 status=Job.IN_PROGRESS)
        unpaid_new = self.new_job()                                      # waiting at the till: not owed yet
        ids = set(owing.owing_jobs([self.branch.pk]).values_list('pk', flat=True))
        self.assertEqual(ids, {job.pk, deposit.pk})
        self.assertNotIn(unpaid_new.pk, ids)

        from apps.eye.services import money
        self.assertEqual(money.owed([self.branch.pk])['job_balances'], Decimal('330.00'))

        from apps.communications.assistant import boss_tools
        with patch.object(boss_tools, 'branches', return_value=([self.branch], None)):
            owes = boss_tools.who_owes()
        self.assertEqual(owes['job_balances']['total'], 'GHS 330.00')
        dwumfour = next(r for r in owes['job_balances']['biggest_first'] if 'Dwumfour' in r['customer'])
        self.assertEqual(dwumfour['owes'], 'GHS 330.00')

    def test_the_cashier_sees_it_with_the_other_balances(self):
        job = ProformaEngine(self.branch).record_owed(self.expired(), self.bm)
        api = APIClient()
        api.force_authenticate(self.cashier)
        r = api.get('/api/v1/jobs/cashier/balances/')
        row = next(x for x in r.data['results'] if x['id'] == job.pk)
        self.assertEqual(row['balance_due'], '300.00')
        self.assertEqual(row['handover_state'], 'HANDED_OVER')
        self.assertEqual(r.data['total'], '300.00')


class StatementTests(Base):

    def test_owed_from_before_new_work_and_the_total(self):
        old = ProformaEngine(self.branch).record_owed(self.expired(), self.bm)
        new = self.new_job('40.00')
        st = owing.statement(self.dwumfour)
        self.assertEqual([j.pk for j in st['owed']], [old.pk])
        self.assertEqual([j.pk for j in st['current']], [new.pk])
        self.assertEqual((st['owed_total'], st['current_total'], st['total']),
                         (Decimal('300.00'), Decimal('40.00'), Decimal('340.00')))

    def test_an_unpaid_job_left_months_ago_is_not_on_it(self):
        stale = self.new_job()
        Job.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(days=90))
        self.assertEqual(owing.statement(self.dwumfour)['current'], [])

    def test_the_pdf_and_the_api(self):
        ProformaEngine(self.branch).record_owed(self.expired(), self.bm)
        self.new_job('40.00')
        pdf = build_statement_pdf(owing.statement(self.dwumfour), self.branch)
        self.assertTrue(pdf.startswith(b'%PDF'))
        from pypdf import PdfReader
        import io
        text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
        for words in ('STATEMENT', 'Owed from before', 'New work', 'GHS 340.00', 'job number'):
            self.assertIn(words, text)
        api = APIClient()
        api.force_authenticate(self.cashier)
        r = api.get(f'/api/v1/finance/customers/{self.dwumfour.pk}/statement/')
        self.assertEqual((r.data['owed_total'], r.data['current_total'], r.data['total']),
                         ('300.00', '40.00', '340.00'))
        self.assertEqual(api.get(f'/api/v1/finance/customers/{self.dwumfour.pk}/statement/pdf/').status_code, 200)

    def test_a_refused_send_is_said_plainly(self):
        # Outside the window it goes as the approved account_statement message
        # (tests_media_templates); here WhatsApp isn't set up, so it's refused.
        ProformaEngine(self.branch).record_owed(self.expired(), self.bm)
        api = APIClient()
        api.force_authenticate(self.bm)
        r = api.post(f'/api/v1/finance/customers/{self.dwumfour.pk}/statement/send/')
        self.assertEqual(r.status_code, 400)
        self.assertIn('approved statement message may not be ready yet', r.data['detail'])

    def test_sent_in_his_chat_when_it_is_open(self):
        from apps.communications.models import Conversation, Message
        from apps.finance.services.statement_pdf import send_statement
        ProformaEngine(self.branch).record_owed(self.expired(), self.bm)
        chat = Conversation.objects.create(channel=Conversation.WHATSAPP, contact_phone='+233555000777',
                                           customer=self.dwumfour)
        Message.objects.create(conversation=chat, direction=Message.INBOUND, channel=Message.WHATSAPP, body='Hi')
        with self.captureOnCommitCallbacks(execute=False):
            sent, why = send_statement(self.dwumfour, self.branch)
        self.assertTrue(sent, why)
        out = chat.messages.get(kind='statement')
        self.assertEqual(out.message_type, Message.DOCUMENT)
        self.assertIn('GHS 300.00 in all', out.body)
        self.assertIn('tell us which one you are paying for', out.body)


class PayingTests(Base):

    def test_he_points_at_the_old_job_and_its_balance_is_taken(self):
        from apps.jobs.services.balance_service import confirm_balance
        job = ProformaEngine(self.branch).record_owed(self.expired(), self.bm)
        with patch('apps.jobs.services.cashier_service._issue_receipt'):
            result = confirm_balance(job, {'payment_method': 'CASH', 'cash_tendered': Decimal('300.00')},
                                     self.cashier)
        job.refresh_from_db()
        self.assertEqual(result['amount_paid'], '300.00')
        self.assertEqual(job.payment_state, 'SETTLED')
        self.assertNotIn(job.pk, set(owing.owing_jobs().values_list('pk', flat=True)))

    def test_a_job_waiting_at_the_till_still_goes_through_the_queue(self):
        from apps.jobs.services.balance_service import check_balance_request
        with self.assertRaisesMessage(ValueError, 'Take its payment from the queue'):
            check_balance_request('UNPAID', '40.00', 'CASH', handover_state='AWAITING_COLLECTION')


class RenewTests(Base):

    def test_the_same_lines_at_todays_prices(self):
        p = self.expired(quantity=5)
        PricingRule.objects.filter(service=self.service).update(base_price=Decimal('12.00'))
        from django.core.cache import cache
        cache.clear()                                                    # prices are cached for a while
        fresh = ProformaEngine(self.branch).renew(p, self.bm)
        self.assertEqual(fresh.status, ProformaInvoice.Status.ISSUED)
        self.assertEqual(fresh.total, Decimal('60.00'))
        self.assertIn(f'Renewed from {p.proforma_number}', fresh.notes)
        p.refresh_from_db()
        self.assertEqual(p.status, ProformaInvoice.Status.EXPIRED)


class ExpiryEveTests(Base):

    def test_the_day_before_the_manager_is_asked_whether_the_work_was_done(self):
        from apps.jobs.tasks import remind_open_proformas
        engine = ProformaEngine(self.branch)
        p = engine.create(customer=self.dwumfour, raw_lines=[{'service': self.service.pk, 'quantity': 1, 'pages': 1}],
                          actor=self.bm)
        engine.issue(p, actor=self.bm)
        ProformaInvoice.objects.filter(pk=p.pk).update(
            issued_at=timezone.now() - timedelta(days=20), valid_until=timezone.localdate() + timedelta(days=1))
        with patch('apps.notifications.services.notify') as notify:
            remind_open_proformas()
        self.assertIn('expires tomorrow. Was the work done?', notify.call_args.kwargs['message'])


class OwnerLineTests(Base):

    def test_octos_records_it_and_reads_the_statement(self):
        from apps.communications.assistant import boss_tools
        p = self.expired()
        with patch('apps.accounts.system.octos_user', return_value=self.bm):
            done = boss_tools.record_owed(p.proforma_number[-5:])
        self.assertEqual(done['owes_on_it'], 'GHS 300.00')
        self.new_job('40.00')
        st = boss_tools.statement('Mr Dwumfour')
        self.assertEqual(st['owed_total'], 'GHS 300.00')
        self.assertEqual(st['new_work_total'], 'GHS 40.00')
        self.assertEqual(st['total_due'], 'GHS 340.00')
