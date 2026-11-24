"""
Fixes from reading Tuesday's chats (24 Nov 2026):

  Loretta     her "Yes please" to the payment link was blocked: the reply said
              7:30pm, the closing time Octos had given her twenty minutes
              earlier in another run. Today's hours, and the clock times Octos
              already gave, may be repeated; prices are always looked up again.
  Adodo       held for the attendant, then two minutes later Octos asked her to
              send her files again, a second after her job was made.
  Elizabeth   "You're welcome" after her receipt got a thank-you and a request
              for her number. It only closes the chat.
  late ones   Loretta (7:29pm) and Nene (7:27pm) were never thanked: the last
              run was at 7:25pm. Now three hours after their last job, even
              after closing (Khofi).

Run: docker compose run --rm web python manage.py test apps.communications.tests_chat_review_24nov -t .
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.communications.assistant import brain, checker, counter
from apps.communications.assistant.brain import Context
from apps.communications.models import AssistantRun
from apps.communications.tests import make_conversation, make_org
from apps.communications.tests_chat_review_23nov import outbound
from apps.communications.tests_week_review import inbound
from apps.jobs.models import Job
from apps.spine import presence
from apps.storefront.services import thanks


class AlreadyKnownTests(TestCase):

    def setUp(self):
        self.chat = make_conversation(None, contact_phone='+233244000199', contact_name='Loretta')
        self.now = timezone.now()

    def known(self, branches=()):
        return brain._already_known(self.chat, Context(self.chat, list(branches)), self.now)

    def test_a_closing_time_octos_gave_earlier_may_be_repeated(self):
        outbound(self.chat, 'Westland closes at 7:30pm today, so we are open for about another 45 minutes.',
                 ago=timedelta(minutes=20))
        reply = 'Here is your payment link. It will be ready before we close at 7:30pm.'
        self.assertEqual(checker.unverified(reply, '[]' + self.known()), [])

    def test_prices_are_never_taken_from_earlier_messages(self):
        outbound(self.chat, '1 colour copy, 4 pages on A4: total GHS 10.00.', ago=timedelta(minutes=20))
        self.assertEqual(checker.unverified('Your total is GHS 10.00.', '[]' + self.known()), ['GHS 10.00'])

    def test_a_teammate_s_words_or_yesterday_s_are_not_octos_s(self):
        from apps.communications.tests import make_user
        outbound(self.chat, 'We close at 7:30pm', ago=timedelta(minutes=20), sent_by=make_user('tm-24@farhat.test', make_org('-TM')))
        outbound(self.chat, 'Ready about 4:10pm', ago=timedelta(hours=13))
        self.assertEqual(checker.unverified('We close at 7:30pm, ready at 4:10pm', '[]' + self.known()),
                         ['4:10pm', '7:30pm'])

    def test_today_s_hours_at_the_branches_are_known(self):
        branch = make_org('-HR')
        hours = {'branch': 'Westland', 'today': {'opens': '7:30am', 'closes': '7:30pm'}}
        with patch('apps.communications.assistant.tools.branch_hours', return_value=hours):
            self.assertEqual(checker.unverified('We close at 7:30pm', '[]' + self.known([branch])), [])

    def test_hours_that_fail_to_load_only_mean_nothing_extra_is_known(self):
        branch = make_org('-HF')
        with patch('apps.communications.assistant.tools.branch_hours', side_effect=RuntimeError('no')):
            self.assertEqual(checker.unverified('We close at 7:30pm', '[]' + self.known([branch])), ['7:30pm'])


class HeldThenDealtWithTests(TestCase):

    def setUp(self):
        self.branch = make_org('-AD')
        self.chat = make_conversation(None, contact_phone='+233244008080', contact_name='Adodo')
        self.trigger = inbound(self.chat, "Check out adodo's document. Open the shared document: https://acrobat.adobe.com/x",
                               ago=timedelta(minutes=2))
        AssistantRun.objects.create(conversation=self.chat, trigger=self.trigger, mode='live',
                                    decision=AssistantRun.SKIPPED,
                                    reason='held for the attendant: not sure where they are (p=0.56)')
        belief = presence.Belief(p=0.56, band=presence.UNSURE, texture='words', reasons=['signed qr 8 min ago'])
        for p in (patch('apps.spine.presence.for_message', return_value=belief),
                  patch('apps.communications.assistant.counter.shop_open', return_value=True),
                  patch('apps.communications.services.opened.in_focus', return_value=False)):
            p.start()
            self.addCleanup(p.stop)

    def test_a_job_made_while_held_keeps_octos_out(self):
        job = Job.objects.create(branch=self.branch, job_type=Job.INSTANT, title='Printing',
                                 estimated_cost=Decimal('14.00'))
        self.chat.jobs.add(job)
        said, why = counter.step(self.chat, self.trigger, timezone.now())
        self.assertIsNone(said)
        self.assertTrue(why.startswith('held for the attendant, who dealt with it: job '), why)

    def test_nothing_done_and_octos_answers(self):
        self.assertIsNone(counter.step(self.chat, self.trigger, timezone.now()))


class YoureWelcomeTests(TestCase):

    def setUp(self):
        self.chat = make_conversation(None, contact_phone='', contact_name='Elizabeth')
        self.receipt = outbound(self.chat, 'Hello there, here is your receipt from Farhat Printing Press for GHS 5.00.',
                                kind='receipt', ago=timedelta(minutes=2))

    def test_you_re_welcome_only_closes_the_chat(self):
        for words in ("You're welcome", 'You are welcome', 'My pleasure', 'Welcome', "you're most welcome"):
            with self.subTest(words=words):
                self.assertTrue(brain._just_acknowledging(inbound(self.chat, words), self.receipt))

    def test_a_welcome_with_a_request_is_not_a_goodbye(self):
        self.assertFalse(brain._just_acknowledging(
            inbound(self.chat, "You're welcome, can you print it again in colour"), self.receipt))


class LateThanksTests(TestCase):

    def setUp(self):
        self.branch = make_org('-LT')
        self.chat = make_conversation(None, contact_phone='+233244000199', contact_name='Loretta')
        self.job = Job.objects.create(branch=self.branch, job_type=Job.INSTANT, title='Printing',
                                      estimated_cost=Decimal('12.00'))
        served = patch.object(thanks, 'chats_served_today', return_value=[(self.chat, None, self.job)])
        self.thank = patch.object(thanks, 'thank', return_value=object())
        for p in (served, self.thank):
            p.start()
            self.addCleanup(p.stop)

    def run_at(self, after):
        thanks.thank.reset_mock()
        return thanks.thank_branch(self.branch, now=self.job.created_at + after)

    def test_not_before_three_hours_after_their_last_job(self):
        self.assertEqual(self.run_at(timedelta(hours=2, minutes=55)), 0)
        thanks.thank.assert_not_called()

    def test_three_hours_on_they_are_thanked(self):
        self.assertEqual(self.run_at(timedelta(hours=3, minutes=1)), 1)


class SharedLinkRuleTests(TestCase):

    def test_octos_asks_for_the_file_without_talking_about_itself(self):
        from apps.communications.assistant import prompt
        self.assertIn('A link to a shared document (Adobe Acrobat', prompt.RULES)
        self.assertIn("Never say you can't open links", prompt.RULES)
