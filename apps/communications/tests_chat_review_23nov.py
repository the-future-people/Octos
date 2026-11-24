"""
Fixes from reading Monday's chats (23 Nov 2026), one class each:

  thank-yous     a customer with a WhatsApp username and no number is thanked too
  quiet files    a customer who answered Octos's follow-up isn't handed over as quiet
  the reminder   nobody is reminded about a customer who said no and goodbye
  goodbyes       "No please" then "Thank you" waits for nothing; emoji alone after a receipt too
  welcome back   a customer seen earlier today is welcomed back, not greeted like a stranger
  receipts       one caption everywhere: their name and the amount, as the template says
  the owner      Octos knows Khofi Adjei, says who it is (never who it isn't), praises back

Run: docker compose run --rm web python manage.py test apps.communications.tests_chat_review_23nov -t .
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.communications.assistant import brain, counter, prompt
from apps.communications.models import Conversation, Message
from apps.communications.services import handover
from apps.communications.services.quiet_remote import flag_quiet
from apps.communications.tests import make_conversation, make_org
from apps.communications.tests_week_review import inbound
from apps.customers.models import CustomerProfile
from apps.finance.receipt_engine import receipt_caption
from apps.jobs.models import Job
from apps.spine import kinds
from apps.spine.models import Event, Visit
from apps.spine.recorder import record
from apps.storefront.services import thanks


def outbound(chat, body, ago=None, **fields):
    m = Message.objects.create(conversation=chat, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
                               body=body, **fields)
    if ago is not None:
        Message.objects.filter(pk=m.pk).update(created_at=timezone.now() - ago)
        m.refresh_from_db()
    return m


def paid_job(branch, customer=None):
    return Job.objects.create(
        branch=branch, job_type=Job.INSTANT, title='Printing', customer=customer, status=Job.PAID,
        payment_state=Job.Payment.SETTLED, estimated_cost=Decimal('20.00'), amount_paid=Decimal('20.00'))


class UsernameThanksTests(TestCase):
    """Kay, Mc James, Kweku, S.K. Doh, Sylvia: served, receipted, never thanked."""

    def setUp(self):
        self.branch = make_org('-TY')
        self.branch.is_trading = True
        self.branch.save()
        self.chat = make_conversation(None, contact_phone='', contact_name='Kay')
        Conversation.objects.filter(pk=self.chat.pk).update(contact_user_id='GH.5450', contact_username='k_kwarteng')
        self.chat.refresh_from_db()
        inbound(self.chat, 'WESTLAND.pdf', ago=timedelta(hours=4))
        for p in (patch('apps.notifications.services.notify_many'),
                  patch.object(thanks, 'AFTER_SERVED', timedelta(0))):    # jobs here are made just now
            p.start()
            self.addCleanup(p.stop)

    def thanked(self):
        return list(self.chat.messages.filter(kind=thanks.KIND).values_list('body', flat=True))

    def test_a_username_chat_linked_to_a_paid_job_is_thanked_once(self):
        self.chat.jobs.add(paid_job(self.branch))
        self.assertEqual(thanks.thank_branch(self.branch), 1)
        [said] = self.thanked()
        self.assertTrue(said.startswith('Thank you for choosing'))
        self.assertNotIn('Kay', said)            # a WhatsApp profile is never a name
        self.assertEqual(thanks.thank_branch(self.branch), 0)

    def test_nothing_unpaid_on_it(self):
        job = paid_job(self.branch)
        Job.objects.filter(pk=job.pk).update(payment_state=Job.Payment.UNPAID, status=Job.PENDING_PAYMENT)
        self.chat.jobs.add(job)
        self.assertEqual(thanks.thank_branch(self.branch), 0)

    def test_a_customer_with_a_number_and_a_linked_chat_is_thanked_once(self):
        ama = CustomerProfile.objects.create(first_name='Ama', phone='+233244000731', customer_type='INDIVIDUAL')
        theirs = make_conversation(None, contact_phone='+233244000731', contact_name='Ama', customer=ama)
        inbound(theirs, 'Hi', ago=timedelta(hours=3))
        job = paid_job(self.branch, customer=ama)
        theirs.jobs.add(job)
        self.assertEqual(thanks.thank_branch(self.branch), 1)
        self.assertEqual(theirs.messages.filter(kind=thanks.KIND).count(), 1)
        self.assertIn('Ama', theirs.messages.get(kind=thanks.KIND).body)


@override_settings(OCTOS_ASSISTANT_MODE='live', ANTHROPIC_API_KEY='test-key')
class QuietAfterAnswerTests(TestCase):
    """Kwabena: followed up at 08:50, answered "No please", "Thank you", flagged at 09:30."""

    def setUp(self):
        self.branch = make_org('-QA')
        kwabena = CustomerProfile.objects.create(first_name='Kwabena', phone='+233244003058',
                                                 customer_type='INDIVIDUAL')
        self.chat = make_conversation(None, contact_phone='+233244003058', contact_name='Kwabena',
                                      customer=kwabena)
        self.now = timezone.now()
        for p in (patch('apps.communications.assistant.counter.shop_open', return_value=True),
                  patch('apps.notifications.services.notify_many')):
            p.start()
            self.addCleanup(p.stop)
        inbound(self.chat, message_type=Message.DOCUMENT, media_id='m-kw', ago=timedelta(minutes=40))
        record(kinds.MESSAGE_RECEIVED, actor=Event.CUSTOMER, conversation=self.chat,
               occurred_at=self.now - timedelta(minutes=40), key='wa:kw-1', payload={'has_file': True})
        self.visit = Visit.objects.get(conversation=self.chat, closed_at__isnull=True)

    def follow_up_says(self, words):
        from apps.communications.tests_assistant_brain import Model, says, text
        return patch('anthropic.Anthropic', return_value=Model(says(text(words))))

    def test_an_answer_to_the_follow_up_is_not_going_quiet(self):
        with self.follow_up_says('Would you like the assignment printed?'):
            self.assertEqual(flag_quiet(self.now), 0)
        inbound(self.chat, 'No please')
        inbound(self.chat, 'Thank you')
        Visit.objects.filter(pk=self.visit.pk).update(last_activity_at=self.now)
        self.assertEqual(flag_quiet(self.now + timedelta(minutes=34)), 0)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.handled_by, Conversation.OCTOS)

    def test_no_answer_still_brings_in_a_person(self):
        with self.follow_up_says('Would you like the assignment printed?'):
            self.assertEqual(flag_quiet(self.now), 0)
        self.assertEqual(flag_quiet(self.now + timedelta(minutes=31)), 1)


class ClosingTests(TestCase):

    def setUp(self):
        self.chat = make_conversation(None, contact_phone='+233244006335', contact_name='Emmanuel')

    def test_no_please_then_thank_you_after_a_question_waits_for_nothing(self):
        outbound(self.chat, 'Should I print the African studies assignment?', ago=timedelta(minutes=5))
        inbound(self.chat, 'No please', ago=timedelta(minutes=4))
        inbound(self.chat, 'Thank you', ago=timedelta(minutes=4) - timedelta(seconds=10))
        self.assertIsNone(handover.waiting_since(self.chat))

    def test_a_bare_no_or_a_goodbye_straight_after_a_question_still_waits(self):
        outbound(self.chat, 'Colour or black and white?', ago=timedelta(minutes=5))
        inbound(self.chat, 'Ok', ago=timedelta(minutes=4))
        self.assertIsNotNone(handover.waiting_since(self.chat))
        inbound(self.chat, 'No', ago=timedelta(minutes=3))
        self.assertIsNotNone(handover.waiting_since(self.chat))

    def test_a_request_then_thanks_waits(self):
        outbound(self.chat, 'Here is your receipt.', ago=timedelta(minutes=5))
        inbound(self.chat, 'Can you print 5 more copies?', ago=timedelta(minutes=4))
        inbound(self.chat, 'Thank you', ago=timedelta(minutes=3))
        self.assertIsNotNone(handover.waiting_since(self.chat))

    def test_praying_hands_after_a_receipt_only_close_the_chat(self):
        outbound(self.chat, 'Hello Emmanuel, here is your receipt.', kind='receipt', ago=timedelta(minutes=25))
        first = inbound(self.chat, '🙏🏼🤦🏽‍♂️🤦🏽‍♂️', ago=timedelta(minutes=3))
        last = inbound(self.chat, '🙏🏼🙏🏼🙏🏼', ago=timedelta(minutes=2))
        self.assertTrue(brain._just_acknowledging(last, first))
        self.assertIsNone(handover.waiting_since(self.chat))

    def test_a_wave_or_a_question_mark_is_not_a_goodbye(self):
        before = outbound(self.chat, 'Here is your receipt.', ago=timedelta(minutes=5))
        self.assertFalse(brain._just_acknowledging(inbound(self.chat, '👋'), before))
        self.assertFalse(brain._just_acknowledging(inbound(self.chat, '??'), before))


class WelcomeBackTests(TestCase):
    """Hermann came back at 15:19 for a second job and was greeted like a stranger."""

    def setUp(self):
        hermann = CustomerProfile.objects.create(first_name='Hermann', phone='+233244003604',
                                                 customer_type='INDIVIDUAL')
        self.chat = make_conversation(None, contact_phone='+233244003604', contact_name='Hermann',
                                      customer=hermann)
        self.now = timezone.localtime().replace(hour=15, minute=19)

    def hello(self):
        m = inbound(self.chat, 'Hello')
        Message.objects.filter(pk=m.pk).update(created_at=self.now)
        m.refresh_from_db()
        return counter.unsure_greeting(self.chat, m, self.now)

    def test_someone_served_earlier_today_is_welcomed_back_by_name(self):
        m = inbound(self.chat, 'Hi')
        Message.objects.filter(pk=m.pk).update(created_at=self.now.replace(hour=11, minute=53))
        self.assertEqual(self.hello(), 'Welcome back, Hermann \U0001F60A How can I help you this time?')

    def test_a_first_hello_today_is_the_plain_greeting(self):
        m = inbound(self.chat, 'Hi')
        Message.objects.filter(pk=m.pk).update(created_at=self.now - timedelta(days=1))
        self.assertEqual(self.hello(), counter.NOT_SURE_GREETING)


class ReceiptCaptionTests(SimpleTestCase):

    def test_the_caption_says_the_name_and_the_amount(self):
        self.assertEqual(receipt_caption('Hermann', Decimal('35')),
                         'Hello Hermann, here is your receipt from Farhat Printing Press for GHS 35.00. '
                         'Thank you for choosing Farhat 🙏')

    def test_no_name_reads_hello_there_like_the_template(self):
        self.assertTrue(receipt_caption('', Decimal('1967.48')).startswith('Hello there, here is your receipt'))
        self.assertIn('GHS 1,967.48', receipt_caption('', Decimal('1967.48')))


class OwnerAndPraiseTests(SimpleTestCase):

    def test_octos_knows_khofi_and_says_who_it_is(self):
        self.assertIn('Khofi Adjei', prompt.RULES)
        self.assertIn("This is Octos, Khofi's assistant", prompt.RULES)
        self.assertIn('never say who you are not', prompt.RULES)

    def test_no_talk_of_tools_or_lists(self):
        self.assertIn('never about your tools', prompt.RULES)
        self.assertIn('"on my side"', prompt.RULES)

    def test_praise_gets_one_warm_line(self):
        self.assertIn('Praise is different from a goodbye', prompt.RULES)


class NoReminderAfterGoodbyeTests(TestCase):
    """Kwabena's "No please", "Thank you" reached staff as a customer waiting 64 minutes."""

    def setUp(self):
        self.chat = make_conversation(None, contact_phone='+233244003058', contact_name='Kwabena')
        outbound(self.chat, 'Should I print the African studies assignment?', ago=timedelta(minutes=66))
        inbound(self.chat, 'No please', ago=timedelta(minutes=65))
        inbound(self.chat, 'Thank you', ago=timedelta(minutes=64))
        Conversation.objects.filter(pk=self.chat.pk).update(
            handled_by=Conversation.STAFF, handled_since=timezone.now() - timedelta(minutes=31))
        self.owner = patch('apps.communications.services.owner_line.customer_waiting')
        for p in (patch('apps.notifications.services.notify_many'), self.owner):
            p.start()
            self.addCleanup(p.stop)

    def test_nobody_is_reminded(self):
        self.assertEqual(handover.watch(), (0, 0))
        self.assertFalse(Event.objects.filter(conversation=self.chat, kind=kinds.STAFF_REMINDED).exists())
