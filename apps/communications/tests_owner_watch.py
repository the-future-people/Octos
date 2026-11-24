"""
Octos acting on the boss's word (19 Nov 2026).

He read a "customer waiting" alert and told his line: "Respond to the
message and see what he wants. Report back." Then: "Check back in a bit."
Octos could only look. Now it can let Octos answer the customer, tell him
when the customer replies, and come back later to look again.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.communications.assistant import boss, boss_tools
from apps.communications.models import Conversation, Message, OwnerMessage, OwnerReminder, OwnerWatch
from apps.communications.services import owner_watch
from apps.communications.tests_owner_boss import BossBase, looks, model, said, turn
from apps.communications.tests_owner_line import meta
from apps.communications.tests_whatsapp import WebhookTestCase, delivery, text


class ChatBase(BossBase):

    def setUp(self):
        super().setUp()
        self.chat = Conversation.objects.create(
            channel=Conversation.WHATSAPP, contact_phone='+233244123456', customer=self.ama,
            handled_by=Conversation.STAFF, assigned_to=self.attendant, handled_since=timezone.now())
        Message.objects.create(conversation=self.chat, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
                               body='Your quote is GHS 5.00')
        self.asked = Message.objects.create(conversation=self.chat, direction=Message.INBOUND,
                                            channel=Message.WHATSAPP, body='How will it come out??')

    def customer(self, words, **extra):
        return Message.objects.create(conversation=self.chat, direction=Message.INBOUND,
                                      channel=Message.WHATSAPP, body=words, **extra)

    def octos(self, words):
        return Message.objects.create(conversation=self.chat, direction=Message.OUTBOUND,
                                      channel=Message.WHATSAPP, body=words)


@override_settings(OCTOS_ASSISTANT_MODE='live')
class AnswerNowTests(ChatBase):

    def test_from_staff_octos_takes_it_and_answers_at_once(self):
        with patch('apps.communications.tasks.answer_whatsapp.apply_async') as answer, \
                self.captureOnCommitCallbacks(execute=True):
            got = owner_watch.answer_now(self.chat)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.handled_by, Conversation.OCTOS)
        self.assertEqual((got['answered'], got['was_with']), (True, 'Test Attendant'))
        answer.assert_called_once()
        self.assertEqual(answer.call_args.args[0], (self.chat.pk, self.asked.pk))

    def test_already_octos_and_waiting_octos_answers(self):
        Conversation.objects.filter(pk=self.chat.pk).update(handled_by=Conversation.OCTOS)
        self.chat.refresh_from_db()
        with patch('apps.communications.tasks.answer_whatsapp.apply_async') as answer, \
                self.captureOnCommitCallbacks(execute=True):
            got = owner_watch.answer_now(self.chat)
        self.assertTrue(got['answered'])
        answer.assert_called_once()

    def test_nobody_waiting_nothing_is_sent_and_he_is_told_why(self):
        self.octos('Here is your preview')
        with patch('apps.communications.tasks.answer_whatsapp.apply_async') as answer, \
                self.captureOnCommitCallbacks(execute=True):
            got = owner_watch.answer_now(self.chat)
        self.assertFalse(got['answered'])
        self.assertIn('the last word in the chat is ours', got['say'])
        answer.assert_not_called()


class WatchTests(ChatBase):

    def test_their_reply_is_reported_with_how_it_was_answered(self):
        owner_watch.watch(self.chat)
        with patch('apps.communications.tasks.report_watched_chat.apply_async') as later, \
                self.captureOnCommitCallbacks(execute=True):
            reply = self.customer('Whole photo is fine')
            owner_watch.customer_wrote(self.chat, reply)
        self.assertEqual(later.call_args.kwargs['countdown'], owner_watch.REPORT_AFTER)
        self.octos('Great! Here is your payment link')
        with meta() as m, self.captureOnCommitCallbacks(execute=True):
            owner_watch.report(self.chat.pk, reply.pk)
        body = m.text.call_args.args[1]
        # One Octos: the customer's words, then "I replied" (19 Nov 2026).
        self.assertIn('👀 *Ama Mensah*\n_Ama Mensah said:_\n> Whole photo is fine', body)
        self.assertIn('_I replied:_\n> Great! Here is your payment link', body)
        self.assertNotIn('How will it come out', body)       # already there before the watch
        self.assertIsNotNone(OwnerWatch.objects.get().done_at)  # 'next': one report, then done

    def test_every_reply_keeps_watching(self):
        owner_watch.watch(self.chat, OwnerWatch.KEEP)
        with meta() as m:          # one fake Meta: its message ids never repeat
            first = self.customer('ok')
            with self.captureOnCommitCallbacks(execute=True):
                owner_watch.report(self.chat.pk, first.pk)
            w = OwnerWatch.objects.get()
            self.assertIsNone(w.done_at)
            self.assertEqual(w.reports, 1)
            second = self.customer('Sending another photo', message_type=Message.IMAGE)
            with self.captureOnCommitCallbacks(execute=True):
                owner_watch.report(self.chat.pk, second.pk)
        body = m.text.call_args.args[1]
        self.assertIn('> Sending another photo\n> 📎 1 file', body)
        self.assertNotIn('> ok', body)
        self.assertIn("Test has the chat and hasn't replied yet", body)

    def test_a_burst_reports_once_from_the_last_message(self):
        owner_watch.watch(self.chat)
        one = self.customer('wait')
        self.customer('actually make it 6 copies')
        with meta() as m, self.captureOnCommitCallbacks(execute=True):
            self.assertIsNone(owner_watch.report(self.chat.pk, one.pk))
        m.text.assert_not_called()

    def test_no_watch_no_report(self):
        with patch('apps.communications.tasks.report_watched_chat.apply_async') as later, \
                self.captureOnCommitCallbacks(execute=True):
            owner_watch.customer_wrote(self.chat, self.customer('hello'))
        later.assert_not_called()

    def test_a_watch_runs_out(self):
        w = owner_watch.watch(self.chat)
        OwnerWatch.objects.filter(pk=w.pk).update(ends_at=timezone.now() - timedelta(minutes=1))
        with patch('apps.communications.tasks.report_watched_chat.apply_async') as later, \
                self.captureOnCommitCallbacks(execute=True):
            owner_watch.customer_wrote(self.chat, self.customer('hello'))
        later.assert_not_called()

    def test_watching_again_replaces_the_old_watch(self):
        owner_watch.watch(self.chat)
        owner_watch.watch(self.chat, OwnerWatch.KEEP)
        self.assertEqual(OwnerWatch.objects.filter(done_at__isnull=True).count(), 1)
        owner_watch.stop(self.chat)
        self.assertFalse(OwnerWatch.objects.filter(done_at__isnull=True).exists())


class CheckLaterTests(ChatBase):

    def test_it_comes_back_in_the_minutes_he_gave_within_limits(self):
        self.assertEqual(owner_watch.check_later(20, 'Kings Hub chat'), 20)
        r = OwnerReminder.objects.get()
        self.assertEqual((r.kind, r.what), (OwnerReminder.CHECK, 'Kings Hub chat'))
        self.assertAlmostEqual((r.due_at - timezone.now()).total_seconds(), 20 * 60, delta=5)
        self.assertEqual(owner_watch.check_later(0, 'x'), owner_watch.CHECK_MIN)
        self.assertEqual(owner_watch.check_later(10_000, 'x'), owner_watch.CHECK_MAX)

    def test_saturday_evening_is_kept_and_fires_once(self):
        saturday = timezone.now() + timedelta(days=2)
        r, error = owner_watch.remind_at(saturday, 'thank Mr Hemeng for the big job')
        self.assertIsNone(error)
        self.assertEqual(r.kind, OwnerReminder.REMIND)
        with patch.object(boss, 'follow_up') as follow:
            self.assertEqual(owner_watch.fire_due(), 0)                       # not yet
            self.assertEqual(owner_watch.fire_due(saturday + timedelta(seconds=30)), 1)
            self.assertEqual(owner_watch.fire_due(saturday + timedelta(minutes=2)), 0)   # once only
        follow.assert_called_once()
        self.assertEqual(follow.call_args.kwargs['kind'], OwnerReminder.REMIND)

    def test_times_it_refuses(self):
        self.assertEqual(owner_watch.remind_at(timezone.now() - timedelta(hours=1), 'x')[1],
                         'That time has already passed.')
        self.assertIn('more than 60 days', owner_watch.remind_at(timezone.now() + timedelta(days=90), 'x')[1])

    def test_a_reminder_that_fails_does_not_stop_the_others(self):
        owner_watch.check_later(2, 'a')
        owner_watch.check_later(2, 'b')
        with patch.object(boss, 'follow_up', side_effect=[RuntimeError('down'), 'ok']) as follow:
            self.assertEqual(owner_watch.fire_due(timezone.now() + timedelta(minutes=3)), 2)
        self.assertEqual(follow.call_count, 2)

    def test_the_reminder_reminds_him(self):
        fake, use = model(turn(said('⏰ Reminder, boss: thank Mr Hemeng for the big job. Shall I draft it?')))
        with meta() as m, use:
            boss.follow_up('thank Mr Hemeng for the big job', timezone.now().isoformat(), kind='REMIND')
        self.assertTrue(m.text.call_args.args[1].startswith('⏰ Reminder, boss:'))
        asked = [t['content'] for t in fake.calls[0]['messages'] if t['role'] == 'user'
                 and isinstance(t['content'], str)]
        self.assertIn('asked you to remind him now: "thank Mr Hemeng for the big job"', asked[-1])

    def test_when_the_time_comes_octos_looks_and_reports(self):
        fake, use = model(
            turn(looks('read_chat', chat_id=self.chat.pk)),
            turn(said('Nothing new from Ama, boss. Still waiting on her answer.')),
        )
        with meta() as m, use:
            boss.follow_up('Kings Hub chat', timezone.now().isoformat())
        self.assertEqual(m.text.call_args.args[1], 'Nothing new from Ama, boss. Still waiting on her answer.')
        asked = [t['content'] for t in fake.calls[0]['messages']
                 if t['role'] == 'user' and isinstance(t['content'], str)]
        self.assertIn('he asked you to check back on this: "Kings Hub chat"', asked[-1])


@override_settings(OCTOS_ASSISTANT_MODE='live')
class OnHisWordTests(ChatBase):

    def test_respond_and_report_back_does_both(self):
        fake, use = model(
            turn(said('On it 👀'), looks('answer_now', chat_id=self.chat.pk),
                 looks('watch_chat', 2, chat_id=self.chat.pk)),
            turn(said("Done. I'm answering her now, and I'll tell you when she replies 👍")),
        )
        with patch('apps.communications.tasks.answer_whatsapp.apply_async') as answer:
            m = self.talk('Respond to the message and see what he wants. Report back', use)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.handled_by, Conversation.OCTOS)
        answer.assert_called_once()
        self.assertTrue(OwnerWatch.objects.filter(conversation=self.chat, done_at__isnull=True).exists())
        self.assertIn("I'll tell you when she replies", self.sent(m)[-1][1])

    def test_a_chat_by_the_customers_name(self):
        fake, use = model(
            turn(looks('watch_chat', customer='Ama', until='every')),
            turn(said("I'll tell you each time she writes 👍")),
        )
        self.talk('keep an eye on Ama for me', use)
        self.assertEqual(OwnerWatch.objects.get().mode, OwnerWatch.KEEP)

    def test_the_rules_say_what_he_can_now_ask(self):
        self.assertIn('answer_now: when he says respond', boss.RULES)
        self.assertIn('do both: answer_now, then watch_chat', boss.RULES)
        self.assertIn('You still cannot message staff', boss.RULES)
        names = {t['name'] for t in boss.TOOL_SPECS}
        self.assertTrue({'answer_now', 'watch_chat', 'check_later'} <= names)


class WebhookWatchTests(WebhookTestCase):

    @override_settings(OCTOS_OWNER_PHONE='+233200000000')
    def test_a_watched_customer_writing_through_the_webhook_is_reported(self):
        with patch.object(owner_watch, 'customer_wrote') as wrote, \
                patch('apps.communications.services.whatsapp_inbound.wake_octos'):
            self.deliver(delivery(text('Whole photo is fine')))
        wrote.assert_called_once()
        conversation, message = wrote.call_args.args
        self.assertEqual(message.body, 'Whole photo is fine')



class YourWordsTests(ChatBase):

    def window(self):
        """The customer wrote just now (setUp): the 24-hour window is open."""

    def tap(self, reply_id):
        self.said(reply_id=reply_id)

    def test_his_exact_words_go_from_him_and_the_chat_comes_back(self):
        self.window()
        with patch('apps.communications.tasks.deliver_whatsapp.delay'), \
                self.captureOnCommitCallbacks(execute=True):
            got = owner_watch.send_for_owner(self.chat, 'Payment at the counter is also fine Kings')
        self.assertEqual(got, {'sent': True, 'say': 'Sent to Ama Mensah ✅'})
        out = Message.objects.filter(conversation=self.chat, direction=Message.OUTBOUND).latest('pk')
        self.assertEqual((out.body, out.sent_by), ('Payment at the counter is also fine Kings', self.owner))
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.handled_by, Conversation.OCTOS)   # nobody answers over him

    def test_window_shut_nothing_is_sent_and_he_is_told(self):
        Message.objects.filter(conversation=self.chat).update(created_at=timezone.now() - timedelta(hours=30))
        got = owner_watch.send_for_owner(self.chat, 'Hello')
        self.assertFalse(got['sent'])
        self.assertIn('more than 24 hours ago', got['say'])

    def test_octos_words_wait_for_his_send(self):
        mine = Message.objects.filter(conversation=self.chat, sent_by=self.owner, is_internal_note=False)
        with meta() as m, patch('apps.communications.tasks.deliver_whatsapp.delay'):
            with self.captureOnCommitCallbacks(execute=True):
                owner_watch.draft_for_owner(self.chat, 'No problem Kings, pay at the counter in the morning 😊')
            draft = OwnerMessage.objects.get(ref=f'say:{self.chat.pk}')
            self.assertEqual(draft.draft, 'No problem Kings, pay at the counter in the morning 😊')
            self.assertEqual([b['title'] for b in draft.buttons], ['Send', 'Cancel'])
            self.assertIn('To Ama Mensah', m.buttons.call_args.args[1])
            self.assertFalse(mine.exists())               # nothing goes before his tap

            self.tap(f'say:send:{self.chat.pk}')
            self.assertEqual(mine.get().body, 'No problem Kings, pay at the counter in the morning 😊')
            self.assertIn('Sent to Ama Mensah ✅', m.text.call_args.args[1])

            self.tap(f'say:send:{self.chat.pk}')          # a second tap sends nothing
            self.assertEqual(mine.count(), 1)
            self.assertIn('already been dealt with', m.text.call_args.args[1])

    def test_cancel_sends_nothing(self):
        self.window()
        with meta(), self.captureOnCommitCallbacks(execute=True):
            owner_watch.draft_for_owner(self.chat, 'Hello Kings')
        with meta() as m, self.captureOnCommitCallbacks(execute=True):
            self.tap(f'say:cancel:{self.chat.pk}')
        self.assertIn('Cancelled. Nothing was sent.', m.text.call_args.args[1])
        self.assertFalse(Message.objects.filter(conversation=self.chat, sent_by=self.owner, is_internal_note=False).exists())

    def test_his_own_message_is_you_in_a_report(self):
        owner_watch.watch(self.chat)
        reply = self.customer('ok thanks')
        Message.objects.create(conversation=self.chat, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
                               body='See you tomorrow', sent_by=self.owner)
        with meta() as m, self.captureOnCommitCallbacks(execute=True):
            owner_watch.report(self.chat.pk, reply.pk)
        self.assertIn('_You replied:_\n> See you tomorrow', m.text.call_args.args[1])

    def test_the_boss_brain_sends_his_quoted_words_as_they_are(self):
        self.window()
        fake, use = model(
            turn(looks('send_to_customer', chat_id=self.chat.pk, exact=True,
                       text='Payment at the counter is also fine Kings, thank you')),
            turn(said('Sent to Kings ✅')),
        )
        with patch('apps.communications.tasks.deliver_whatsapp.delay'):
            self.talk('take back the chat and tell him "Payment at the counter is also fine Kings, thank you"', use)
        out = Message.objects.filter(conversation=self.chat, sent_by=self.owner, is_internal_note=False).get()
        self.assertEqual(out.body, 'Payment at the counter is also fine Kings, thank you')

    def test_the_rules(self):
        self.assertIn('one Octos, not two', boss.RULES)
        self.assertIn('never "Octos said"', boss.RULES)
        self.assertIn('word for word, from him', boss.RULES)
        from apps.communications.assistant import prompt
        self.assertIn('would rather pay at the counter can', prompt.RULES)      # reworded 24 Nov 2026 (pay_at_counter)



class SaturdayAndDiscountsTests(ChatBase):

    def test_remind_me_on_saturday_evening(self):
        local = timezone.localtime() + timedelta(days=2)
        at = local.replace(hour=18, minute=0, second=0, microsecond=0)
        fake, use = model(
            turn(looks('remind_me', at=at.strftime('%Y-%m-%dT%H:%M'),
                       what='send Mr Hemeng a special thank you for bringing the job our way')),
            turn(said("I'll remind you at 6:00pm 👍")),
        )
        self.talk('Remind me here on Saturday evening to thank him', use)
        r = OwnerReminder.objects.get()
        self.assertEqual(timezone.localtime(r.due_at).hour, 18)
        self.assertEqual(r.kind, OwnerReminder.REMIND)
        result = fake.calls[1]['messages'][-1]['content'][0]['content']
        self.assertIn('6:00pm', result)

    def test_nothing_waiting_sends_nothing_and_claims_nothing(self):
        fake, use = model(
            turn(looks('waiting_for_you')),
            turn(said('Nothing waiting for your OK, boss.')),
        )
        m = self.talk('anything waiting for me?', use)
        self.assertEqual([w for _, w in self.sent(m)], ['Nothing waiting for your OK, boss.'])
        result = fake.calls[1]['messages'][-1]['content'][0]['content']
        self.assertIn('"nothing_waiting": true', result)

    def test_past_discounts_and_the_proforma_they_were_on(self):
        from decimal import Decimal
        from apps.jobs.models import PriceCut, ProformaInvoice
        p = ProformaInvoice.objects.create(
            branch=self.branch, customer=self.ama, proforma_number='PFI-WLB-2026-00036-v2', sequence=36,
            issued_to='Mr Kwaku Apau Hemeng', valid_until=timezone.localdate() + timedelta(days=21),
            line_items=[], total=Decimal('1967.48'), discount_amount=Decimal('464.52'),
            discount_reason='Large Order', issued_by=self.attendant)
        PriceCut.objects.create(proforma=p, before_total=Decimal('2432.00'), new_total=Decimal('1967.48'),
                                amount=Decimal('464.52'), reason='Large Order', status=PriceCut.Status.APPLIED,
                                asked_by=self.attendant, decided_by=self.owner)
        got = boss_tools.discounts('this_week', 'Test')
        row = got['discounts'][0]
        self.assertEqual((row['on'], row['before'], row['after'], row['off']),
                         ('PFI-WLB-2026-00036-v2', 'GHS 2,432.00', 'GHS 1,967.48', 'GHS 464.52'))
        self.assertEqual((row['asked_by'], row['decided_by']), ('Test Attendant', 'Khofi Owner'))
        self.assertEqual(boss_tools.discounts('this_week', 'Test', 'waiting')['count'], 0)

        found = boss_tools.find_proforma('00036')['proformas'][0]
        self.assertEqual((found['to'], found['total'], found['issued_by']),
                         ('Mr Kwaku Apau Hemeng', 'GHS 1,967.48', 'Test Attendant'))
        self.assertIn('464.52 off', found['discount'])
        self.assertEqual(boss_tools.find_proforma('Hemeng')['found'], 1)
        self.assertEqual(boss_tools.find_proforma('PFI-WLB-2026-00036-v2')['found'], 1)
