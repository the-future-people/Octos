"""
The owner's private WhatsApp line (18 Nov 2026): his messages never become a
chat, reports and urgent matters reach him (now, or waiting behind a knock
when the window is shut), and he can approve a discount from his phone.

The number here is a made-up test number: the real one lives on Railway.
"""
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.communications.models import Conversation, OwnerMessage
from apps.communications.services import owner_cards, owner_line, owner_reports
from apps.communications.tests_whatsapp import PHONE_ID, WebhookTestCase, delivery, text
from apps.jobs.models import Job, JobLineItem, PriceCut, PricingRule, Service
from apps.jobs.pricing_engine import PricingEngine
from apps.jobs.services import discounts
from apps.jobs.tests import JobsFixtureMixin

OWNER = '0244000111'            # made up
OWNER_WA = '233244000111'       # as WhatsApp sends it
CLIENT = 'apps.communications.services.whatsapp_client'


def _wamids(prefix):
    count = iter(range(1, 1000))
    return lambda *a, **k: f'wamid.{prefix}{next(count)}'


@contextmanager
def meta():
    """Meta, faked: every send answers with a new wamid, and the tasks run at once."""
    with patch(f'{CLIENT}.send_text', side_effect=_wamids('T')) as send_text, \
            patch(f'{CLIENT}.send_template', side_effect=_wamids('K')) as send_template, \
            patch(f'{CLIENT}.send_image', side_effect=_wamids('I')) as send_image, \
            patch(f'{CLIENT}.send_buttons', side_effect=_wamids('B')) as send_buttons, \
            patch('apps.communications.tasks.deliver_owner_message.delay', side_effect=owner_line.deliver), \
            patch('apps.communications.tasks.answer_owner.delay', side_effect=owner_line.answer):
        yield SimpleNamespace(text=send_text, template=send_template, image=send_image, buttons=send_buttons)


@override_settings(OCTOS_OWNER_PHONE=OWNER)
class Base(JobsFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = cls.bm.__class__.objects.create(
            employee_id='OWN-T', first_name='Khofi', last_name='Owner', email='own-t@test.local',
            employment_status='ACTIVE', is_active=True, is_business_owner=True, branch=cls.branch)
        cls.colour = Service.objects.create(
            name='A4 Colour Printing', code='OL-COL', category='INSTANT', unit='PER_COPY',
            requires_design=False, requires_file_upload=False, is_active=True, cost_basis=Service.COST_COLOUR)
        PricingRule.objects.create(service=cls.colour, branch=None, base_price=Decimal('2.50'),
                                   color_multiplier=Decimal('1.00'), is_active=True)

    def open_window(self):
        OwnerMessage.objects.create(direction=OwnerMessage.IN, status=OwnerMessage.RECEIVED, body='hi')

    def job(self, pages=314, sets=3):
        price = PricingEngine.get_price(service=self.colour, branch=self.branch, quantity=sets, pages=pages)
        job = Job.objects.create(branch=self.branch, job_type=Job.INSTANT, title='Thesis printing',
                                 status=Job.PENDING_PAYMENT, estimated_cost=price['total'], intake_by=self.bm)
        JobLineItem.objects.create(job=job, service=self.colour, pages=pages, sets=sets, quantity=1,
                                   unit_price=Decimal('2.50'), line_total=price['total'])
        return job

    def said(self, body='', reply_id=''):
        """The owner writes (or taps), and Octos answers."""
        m = OwnerMessage.objects.create(direction=OwnerMessage.IN, status=OwnerMessage.RECEIVED,
                                        body=body, reply_id=reply_id)
        with self.captureOnCommitCallbacks(execute=True):
            owner_line.answer(m.pk)

    def out(self, **filters):
        return OwnerMessage.objects.filter(direction=OwnerMessage.OUT, **filters)


class SendingTests(Base):

    def test_sent_straight_away_when_the_window_is_open(self):
        self.open_window()
        with meta() as m, self.captureOnCommitCallbacks(execute=True):
            owner_line.tell(OwnerMessage.URGENT, 'Plotter is down')
        m.text.assert_called_once_with('+233244000111', 'Plotter is down')
        self.assertEqual(self.out(kind=OwnerMessage.URGENT).get().status, OwnerMessage.SENT)

    def test_window_shut_waits_and_one_template_knocks(self):
        with meta() as m, self.captureOnCommitCallbacks(execute=True):
            owner_line.tell(OwnerMessage.URGENT, 'Plotter is down', knock='The plotter is down.')
            owner_line.tell(OwnerMessage.URGENT, 'Cash short', knock='Cash was short.')
        self.assertEqual(self.out(status=OwnerMessage.WAITING).count(), 2)
        m.template.assert_called_once()
        self.assertEqual(m.template.call_args.args[1], 'owner_update')
        self.assertEqual(m.template.call_args.kwargs['params'], ['The plotter is down.'])
        m.text.assert_not_called()

    def test_his_tap_sends_what_waited_in_order_and_drops_what_is_stale(self):
        with meta(), self.captureOnCommitCallbacks(execute=True):
            owner_line.tell(OwnerMessage.BRIEF, 'Old brief')
            owner_line.tell(OwnerMessage.URGENT, 'Plotter is down')
            owner_line.tell(OwnerMessage.BRIEF, 'New brief')
        with meta() as m:
            self.said('Open', reply_id='open')
        self.assertEqual([c.args[1] for c in m.text.call_args_list], ['Plotter is down', 'New brief'])
        self.assertEqual(self.out(kind=OwnerMessage.BRIEF, body='Old brief').get().status, OwnerMessage.SKIPPED)

    def test_meta_saying_the_window_is_shut_turns_it_into_a_wait(self):
        from apps.communications.services.whatsapp_client import WhatsAppError
        self.open_window()
        with meta() as m, self.captureOnCommitCallbacks(execute=True):
            m.text.side_effect = WhatsAppError('131047', 'Re-engagement message')
            owner_line.tell(OwnerMessage.URGENT, 'Plotter is down')
        self.assertEqual(self.out(kind=OwnerMessage.URGENT).get().status, OwnerMessage.WAITING)
        m.template.assert_called_once()

    @override_settings(OCTOS_OWNER_PHONE='')
    def test_no_number_set_means_no_line(self):
        self.assertIsNone(owner_line.tell(OwnerMessage.URGENT, 'Plotter is down'))
        self.assertFalse(OwnerMessage.objects.exists())

    def test_the_same_event_is_told_once(self):
        self.open_window()
        with meta(), self.captureOnCommitCallbacks(execute=True):
            owner_line.tell(OwnerMessage.URGENT, 'Down', key='machine-down:1:x')
            self.assertIsNone(owner_line.tell(OwnerMessage.URGENT, 'Down', key='machine-down:1:x'))


class DiscountTests(Base):

    def test_a_discount_below_the_floor_reaches_his_phone_with_buttons(self):
        self.open_window()
        with meta() as m, self.captureOnCommitCallbacks(execute=True), patch('apps.notifications.services.notify'):
            cut = discounts.lower(self.bm, '1200', 'He insists', job=self.job())
        self.assertEqual(cut.status, PriceCut.Status.PENDING)
        body, buttons = m.buttons.call_args.args[1], m.buttons.call_args.args[2]
        self.assertRegex(body, r'Price +2,355\.00')
        self.assertRegex(body, r'Asked +1,200\.00')
        self.assertIn('_"He insists"_', body)
        self.assertEqual([b['id'] for b in buttons], [f'cut:approve:{cut.pk}', f'cut:decline:{cut.pk}'])

    def test_approve_from_the_phone(self):
        with patch('apps.notifications.services.notify'):
            cut = discounts.lower(self.bm, '1200', 'He insists', job=self.job())
        with meta() as m, patch('apps.notifications.services.notify'):
            self.said('Approve', reply_id=f'cut:approve:{cut.pk}')
        cut.refresh_from_db()
        self.assertEqual(cut.status, PriceCut.Status.APPLIED)
        self.assertEqual(cut.job.estimated_cost, Decimal('1200.00'))
        self.assertTrue(any('Approved' in c.args[1] for c in m.text.call_args_list))

    def test_decline_from_the_phone(self):
        with patch('apps.notifications.services.notify'):
            cut = discounts.lower(self.bm, '1200', 'He insists', job=self.job())
        with meta(), patch('apps.notifications.services.notify'):
            self.said('Decline', reply_id=f'cut:decline:{cut.pk}')
        cut.refresh_from_db()
        self.assertEqual(cut.status, PriceCut.Status.DECLINED)

    def test_a_waiting_discount_already_decided_is_not_sent_later(self):
        with meta(), self.captureOnCommitCallbacks(execute=True), patch('apps.notifications.services.notify'):
            cut = discounts.lower(self.bm, '1200', 'He insists', job=self.job())
            discounts.approve(self.owner, cut.pk)
        with meta() as m:
            self.said('Open', reply_id='open')
        m.buttons.assert_not_called()


class AnswerTests(Base):

    def setUp(self):
        self.open_window()

    def test_today_is_designed_text(self):
        self.job()
        with meta() as m:
            self.said('Today?')
        text = m.text.call_args.args[1]
        self.assertTrue(text.startswith('📊 *Today so far'))
        self.assertIn('```Jobs taken', text)
        m.image.assert_not_called()

    def test_card_sends_the_picture(self):
        self.job()
        with meta() as m:
            self.said('brief card')
        content, caption = m.image.call_args.args[1], m.image.call_args.kwargs['caption']
        self.assertTrue(content.startswith(b'\x89PNG'))
        self.assertIn('Good morning, Khofi', caption)

    def test_a_job_number(self):
        job = self.job()
        with meta() as m:
            self.said(f'where is {job.job_number[-5:]}')
        self.assertIn(job.job_number, m.text.call_args.args[1])

    def test_hello_gets_the_menu_and_nonsense_says_so(self):
        with meta() as m:
            self.said('Hello')
            self.said('purple elephant')
        first, second = [c.args[1] for c in m.text.call_args_list]
        self.assertIn('Your business line', first)
        self.assertTrue(second.startswith("I didn't catch that"))


class TextTests(TestCase):

    def test_figures_line_up_in_a_fixed_width_block(self):
        self.assertEqual(owner_reports.table([('Jobs taken', 30), ('Promises kept', '100%')]),
                         '```Jobs taken            30\nPromises kept       100%```')

    def test_job_numbers_become_chips_so_they_are_never_phone_links(self):
        self.assertEqual(owner_reports.chips('FP-WLB-2026-05286 halted over a day'),
                         '`FP-WLB-2026-05286` halted over a day')


class ReportTests(Base):

    def test_the_brief_and_close_build_and_draw_from_real_records(self):
        self.job()
        for report in (owner_reports.brief(), owner_reports.close(), owner_reports.snapshot()):
            self.assertTrue(owner_cards.render(report['card']).startswith(b'\x89PNG'))
            self.assertNotIn('\n', report['knock'])
        brief = owner_reports.brief()['text']
        self.assertTrue(brief.startswith('☀️ *Good morning, Khofi*'))
        self.assertIn(owner_reports.RULE, brief)
        self.assertLess(len(brief), 4096)                 # WhatsApp's limit for a text

    def test_the_scheduled_brief_goes_once_a_day(self):
        with meta(), self.captureOnCommitCallbacks(execute=True):
            owner_line.send_brief()
            owner_line.send_brief()
        self.assertEqual(self.out(kind=OwnerMessage.BRIEF).count(), 1)


class UrgentTests(Base):

    def setUp(self):
        self.open_window()

    def test_cash_short_and_not_over(self):
        short = SimpleNamespace(pk=1, variance=Decimal('-40'), cashier_id=1, cashier=self.bm,
                                variance_notes='Change error', expected_cash=Decimal('900'),
                                closing_cash=Decimal('860'))
        over = SimpleNamespace(pk=2, variance=Decimal('5'), cashier_id=1, cashier=self.bm)
        with meta() as m, self.captureOnCommitCallbacks(execute=True):
            owner_line.cash_short(short)
            owner_line.cash_short(over)
        m.text.assert_called_once()
        self.assertIn('Cash short GHS 40.00', m.text.call_args.args[1])

    def test_a_machine_down(self):
        machine = SimpleNamespace(pk=3, name='Roland plotter', branch_id=1, branch=self.branch,
                                  unavailable_since=timezone.now(), unavailable_reason='Head jam')
        with meta() as m, self.captureOnCommitCallbacks(execute=True):
            owner_line.machine_down(machine)
        self.assertIn('Roland plotter is down', m.text.call_args.args[1])

    def test_a_broken_hook_never_breaks_the_work(self):
        with patch.object(owner_line, 'tell', side_effect=RuntimeError('boom')):
            self.assertIsNone(owner_line.machine_down(SimpleNamespace(
                pk=1, name='X', branch_id=None, unavailable_since=None, unavailable_reason='')))


@override_settings(OCTOS_OWNER_PHONE=OWNER)
class WebhookTests(WebhookTestCase):

    def test_his_messages_never_become_a_chat(self):
        with patch('apps.communications.tasks.answer_owner.delay') as answer, \
                self.captureOnCommitCallbacks(execute=True):
            self.deliver(delivery(text('today', wamid='wamid.OWN1', sender=OWNER_WA)))
        self.assertFalse(Conversation.objects.exists())
        got = OwnerMessage.objects.get()
        self.assertEqual((got.direction, got.body), (OwnerMessage.IN, 'today'))
        answer.assert_called_once_with(got.pk)

    def test_a_tapped_button_keeps_its_id(self):
        tap = {'from': OWNER_WA, 'id': 'wamid.OWN2', 'timestamp': '1762270000', 'type': 'interactive',
               'interactive': {'type': 'button_reply', 'button_reply': {'id': 'cut:approve:7', 'title': 'Approve'}}}
        with patch('apps.communications.tasks.answer_owner.delay'):
            self.deliver(delivery(tap))
            self.deliver(delivery(tap))                      # Meta retries: once
        self.assertEqual(OwnerMessage.objects.get().reply_id, 'cut:approve:7')

    def test_customers_are_unchanged(self):
        with patch('apps.communications.services.whatsapp_inbound.wake_octos'):
            self.deliver(delivery(text('Hi, are you open?')))
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertFalse(OwnerMessage.objects.exists())
