"""
Octos on the owner's line, the week of 23 Nov (reviewed with Khofi 26 Nov
2026): stretched thank-yous, the price list, every line of a job, two quick
messages and one answer, a settled reminder, readable job names, the brief
after a Sunday, the alerts, and area prices to the nearest 50 pesewas with
sizes as measured.
"""
import datetime
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.communications.assistant import boss, brain, checker
from apps.communications.models import Message, OwnerMessage
from apps.communications.services import owner_line, owner_reports
from apps.communications.tests_owner_line import OWNER, Base
from apps.jobs.models import Job, JobHalt, JobLineItem, PricingRule, Service
from apps.jobs.pricing_engine import quote_line, to_half
from apps.jobs.services.job_names import job_name, short_ref


def said(body, direction=Message.INBOUND):
    return SimpleNamespace(body=body, direction=direction, media_id='', message_type='TEXT')


class StretchedWordsTests(TestCase):

    def test_thank_youuu_closes_like_thank_you(self):
        receipt = said('Your receipt for GHS 10.00 is attached.', Message.OUTBOUND)
        self.assertTrue(brain.closed_after([said('Thank youuu'), receipt]))
        self.assertTrue(brain.closed_after([said('Okkk thanksss'), receipt]))

    def test_real_words_are_unchanged(self):
        self.assertEqual(brain._plain(said('Good morning, I need 3 copies!')), 'good morning, i need 3 copies')


class JobNameTests(TestCase):

    def test_who_and_what_with_the_short_number(self):
        kwabena = SimpleNamespace(first_name='Kwabena', full_name='Kwabena Mensah', customer_type='INDIVIDUAL',
                                  company_name='')
        job = SimpleNamespace(job_number='FP-WLB-2026-05286', title='Flexy Banner · 3 x 2 ft',
                              customer=kwabena, customer_id=1)
        self.assertEqual(job_name(job), "Kwabena's Flexy Banner (#5286)")
        self.assertEqual(short_ref('FP-WLB-2026-00012'), '#12')

    def test_more_lines_and_walk_ins(self):
        job = SimpleNamespace(job_number='FP-WLB-2026-06246', customer=None, customer_id=None,
                              title='A4 Black & White Printing (both sides) · Front and back and 2 more')
        self.assertEqual(job_name(job), 'Walk-in A4 Black & White Printing (both sides) and 2 more (#6246)')

    def test_the_checker_holds_a_job_number_nobody_looked_up(self):
        self.assertEqual(checker.unverified("Kwabena's banner (#5286) is ready", '{"job": "FP-WLB-2026-05287"}'),
                         ['job #5286'])
        self.assertEqual(checker.unverified("Kwabena's banner (#5286) is ready", '{"job": "FP-WLB-2026-05286"}'),
                         [])


class AreaPriceTests(Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.banner = Service.objects.create(name='Flexy Banner', code='OW-FLX', category='PRODUCTION',
                                            unit='PER_SQFT', is_active=True)
        PricingRule.objects.create(service=cls.banner, branch=None, base_price=Decimal('4.17'), is_active=True)

    def test_to_the_nearest_fifty_pesewas(self):
        self.assertEqual([to_half(v) for v in ('69.54', '84.43', '69.75', '157.13')],
                         [Decimal('69.50'), Decimal('84.50'), Decimal('70.00'), Decimal('157.00')])

    def test_two_pieces_cost_twice_one(self):
        one = quote_line(self.banner, None, {'width_in': 33.5, 'height_in': 78.75}, 1)
        two = quote_line(self.banner, None, {'width_in': 33.5, 'height_in': 78.75}, 2)
        self.assertEqual(one['total'] % Decimal('0.50'), 0)
        self.assertEqual(two['total'], one['total'] * 2)

    def test_a_size_as_measured_is_priced_as_measured(self):
        api = APIClient()
        api.force_authenticate(self.bm)
        got = api.get('/api/v1/jobs/price/calculate/', {'service': self.banner.pk, 'branch': self.branch.pk,
                                                        'width_in': '2.5', 'height_in': '36', 'quantity': 1})
        self.assertEqual(got.status_code, 200, got.data)
        # 2.5 x 36 = 90 sq in = 0.625 sq ft x 4.17 = 2.61 -> 2.50.
        self.assertEqual(Decimal(str(got.data['total'])), Decimal('2.50'))
        refused = api.get('/api/v1/jobs/price/calculate/', {'service': self.banner.pk, 'branch': self.branch.pk,
                                                            'width_in': 'wide', 'height_in': '36'})
        self.assertEqual(refused.status_code, 400)


class BossLookupTests(Base):

    def test_find_job_shows_every_line(self):
        from apps.communications.assistant import boss_tools
        job = self.job(pages=90, sets=1)
        JobLineItem.objects.create(job=job, service=self.colour, pages=40, sets=1, quantity=1,
                                   unit_price=Decimal('2.50'), line_total=Decimal('100.00'))
        found = boss_tools.find_job(job.job_number[-5:])
        row = found['jobs'][0]
        self.assertEqual(len(row['lines']), 2)
        self.assertEqual({line['pages'] for line in row['lines']}, {90, 40})
        self.assertIn(short_ref(job.job_number), row['name'])

    def test_he_can_ask_the_price_list(self):
        found = boss._run_tool('price_list', {'query': 'A4 colour'}, [])
        self.assertIn('OL-COL', [s['code'] for s in found['services']])
        price = boss._run_tool('price', {'service_code': 'OL-COL', 'specifications': {'pages': 4}, 'quantity': 2}, [])
        self.assertTrue(price.get('success'), price)


class GatherTests(Base):

    def test_a_second_message_answers_both(self):
        first = OwnerMessage.objects.create(direction=OwnerMessage.IN, status=OwnerMessage.RECEIVED,
                                            body='No i think i get it now')
        OwnerMessage.objects.create(direction=OwnerMessage.IN, status=OwnerMessage.RECEIVED, body='its correct')
        with patch('apps.communications.assistant.boss.reply') as reply, \
                patch('apps.communications.assistant.boss.available', return_value=True), \
                self.captureOnCommitCallbacks(execute=True):
            owner_line.answer(first.pk)
        reply.assert_not_called()

    def test_his_words_wait_a_moment(self):
        with patch('apps.communications.tasks.answer_owner.apply_async') as later, \
                patch('apps.communications.tasks.answer_owner.delay') as now_, \
                self.captureOnCommitCallbacks(execute=True):
            owner_line.receive({'id': 'wamid.G1', 'type': 'text', 'text': {'body': 'how far'}})
            owner_line.receive({'id': 'wamid.G2', 'type': 'interactive',
                                'interactive': {'type': 'button_reply', 'button_reply': {'id': 'open', 'title': 'Open'}}})
        later.assert_called_once()
        self.assertEqual(later.call_args.kwargs['countdown'], owner_line.GATHER)
        now_.assert_called_once()                         # a tap is answered at once


class SettledReminderTests(Base):

    def test_a_reminder_already_settled_says_nothing(self):
        with patch.object(boss, '_converse', return_value='QUIET'), patch.object(boss, '_say') as say:
            out = boss.follow_up('Ask Khofi if the lights are back', timezone.now().isoformat(), kind='REMIND')
        self.assertEqual(out, '')
        say.assert_not_called()


class ReportTests(Base):

    def test_monday_reports_saturday_against_the_saturday_before(self):
        self.branch.is_trading = True
        self.branch.save()
        monday = datetime.date(2026, 11, 23)
        self.assertEqual(owner_reports.last_open_days(monday),
                         (datetime.date(2026, 11, 21), datetime.date(2026, 11, 14)))
        tuesday = datetime.date(2026, 11, 24)
        self.assertEqual(owner_reports.last_open_days(tuesday),
                         (datetime.date(2026, 11, 23), datetime.date(2026, 11, 21)))
        text = owner_reports.brief(monday)['text']
        self.assertIn('Collected Saturday', text)
        self.assertNotIn('Collected yesterday', text)

    def test_no_promises_no_row(self):
        table = owner_reports._jobs_table({'taken': 3, 'finished': 3, 'kept_pct': None})
        self.assertNotIn('Promises kept', table)
        self.assertIn('Promises kept', owner_reports._jobs_table({'taken': 3, 'finished': 3, 'kept_pct': 90}))

    def test_halted_says_since_when_and_a_cancelled_job_is_no_alert(self):
        from apps.eye.services import alerts, scope
        job = self.job()
        halt = JobHalt.objects.create(job=job, reason='Test', halted_by=self.bm)
        JobHalt.objects.filter(pk=halt.pk).update(halted_at=timezone.now() - timedelta(days=8))
        titles = [a['title'] for a in alerts.compute(scope.resolve('company'))]
        found = [t for t in titles if 'halted since' in t]
        self.assertEqual(len(found), 1, titles)
        self.assertIn(short_ref(job.job_number), found[0])
        self.assertIn('8 days', found[0])
        Job.objects.filter(pk=job.pk).update(status='CANCELLED')
        titles = [a['title'] for a in alerts.compute(scope.resolve('company'))]
        self.assertFalse([t for t in titles if 'halted' in t])

    def test_an_open_sheet_counts_only_where_the_branch_trades(self):
        from apps.eye.services import alerts, scope
        late = timezone.make_aware(datetime.datetime.combine(timezone.localdate(), datetime.time(23, 0)))
        with patch('django.utils.timezone.localtime', return_value=late):
            titles = [a['title'] for a in alerts.compute(scope.resolve('company'))]
        self.assertNotIn('Cash sheet still open after closing', titles)
        self.branch.is_trading = True
        self.branch.save()
        with patch('django.utils.timezone.localtime', return_value=late):
            titles = [a['title'] for a in alerts.compute(scope.resolve('company'))]
        self.assertIn('Cash sheet still open after closing', titles)
