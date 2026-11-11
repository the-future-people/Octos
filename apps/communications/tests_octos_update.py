"""
The 6 Nov 2026 update: the quiet window, counter visits, the batch rule,
crossing messages (Mercy), the bot guard, files read on arrival, the name
once per visit. Opening hours are patched, so these hold at any hour.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.communications.assistant import brain, counter, prompt
from apps.communications.models import AssistantRun, Conversation, Message
from apps.communications.services import whatsapp_inbound, whatsapp_media
from apps.communications.tests import CommunicationsTestBase, make_conversation, make_org
from apps.communications.tests_assistant_brain import Model, says, text

OPEN = 'apps.communications.assistant.counter.shop_open'


@override_settings(ANTHROPIC_API_KEY='test-key', OCTOS_ASSISTANT_MODE='live')
class Base(TestCase):

    def setUp(self):
        branch = make_org()
        branch.is_trading = True
        branch.save()
        self.conv = make_conversation(None, contact_phone='+233244000594')
        alerts = patch('apps.notifications.services.notify_many')
        alerts.start()
        self.addCleanup(alerts.stop)

    def customer(self, body='', file=False):
        return Message.objects.create(
            conversation=self.conv, direction=Message.INBOUND, channel=Message.WHATSAPP,
            message_type=Message.IMAGE if file else Message.TEXT, body=body,
            media_id='m-1' if file else '')

    def octos(self, body):
        return Message.objects.create(
            conversation=self.conv, direction=Message.OUTBOUND, channel=Message.WHATSAPP, body=body)

    def respond(self, model, trigger):
        with patch('anthropic.Anthropic', return_value=model):
            return brain.respond(self.conv.pk, trigger.pk)

    def sent(self):
        return self.conv.messages.filter(direction=Message.OUTBOUND, is_internal_note=False)


class QuietWindowTests(Base):

    def test_words_wait_briefly(self):
        with patch(OPEN, return_value=True):
            self.assertEqual(counter.quiet_window(self.customer('Hello')), counter.WORDS_WAIT)

    def test_a_file_waits_45_seconds_when_closed(self):
        with patch(OPEN, return_value=False):
            self.assertEqual(counter.quiet_window(self.customer(file=True)), counter.CLOSED_WAIT)

    def test_a_file_waits_2_minutes_when_open(self):
        with patch(OPEN, return_value=True):
            self.assertEqual(counter.quiet_window(self.customer(file=True)), counter.OPEN_WAIT)

    def test_a_dot_is_not_words(self):
        with patch(OPEN, return_value=False):
            self.assertEqual(counter.quiet_window(self.customer('.')), counter.CLOSED_WAIT)

    def test_waking_uses_the_quiet_window_and_shows_no_dots_yet(self):
        trigger = self.customer(file=True)
        with patch(OPEN, return_value=False), \
                patch('apps.communications.tasks.answer_whatsapp.apply_async') as wake, \
                patch('apps.communications.services.whatsapp_client.show_typing') as dots, \
                self.captureOnCommitCallbacks(execute=True):
            whatsapp_inbound.wake_octos(self.conv, trigger, pause=8)
        wake.assert_called_once_with((self.conv.pk, trigger.pk), countdown=counter.CLOSED_WAIT)
        dots.assert_not_called()


class CounterTests(Base):

    def setUp(self):
        super().setUp()
        opened = patch(OPEN, return_value=True)
        opened.start()
        self.addCleanup(opened.stop)

    def test_the_qr_message_starts_a_visit_without_the_model(self):
        model = Model(says(text('should not be used')))
        self.respond(model, self.customer("Hi, I'm at the Westland counter"))
        self.assertEqual(model.calls, [])
        said = self.sent().get().body
        self.assertIn('pick them up', said)
        self.assertNotIn('ends in', said)      # no phone digits (11 Nov 2026)
        self.conv.refresh_from_db()
        self.assertTrue(counter.in_visit(self.conv))

    def test_during_a_visit_octos_is_silent(self):
        # A visit that just started (the belief: fresh counter proof, then a statement, stays at the counter)
        Conversation.objects.filter(pk=self.conv.pk).update(counter_until=timezone.now() + counter.VISIT)
        run = self.respond(Model(says(text('x'))), self.customer('Please make it A4'))
        self.assertEqual(run.decision, AssistantRun.SKIPPED)
        self.assertFalse(self.sent().exists())

    def test_a_file_with_no_words_gets_one_message_then_silence(self):
        self.respond(Model(says(text('x'))), self.customer(file=True))
        self.assertEqual(self.sent().get().body, counter.FORK_TEXT)
        run = self.respond(Model(says(text('x'))), self.customer(file=True))
        self.assertEqual(run.decision, AssistantRun.SKIPPED)
        self.assertEqual(self.sent().count(), 1)

    def test_phrases(self):
        self.assertEqual(counter.counter_phrase("Hi, I'm at the Westland counter"), 'westland')
        self.assertEqual(counter.counter_phrase('I am here'), '')
        self.assertIsNone(counter.counter_phrase('How much is A4 colour?'))


class AtTheCounterButtonTests(CommunicationsTestBase):

    def test_the_attendant_starts_a_visit_with_one_tap(self):
        conv = make_conversation(self.branch, contact_phone='+233244000777')
        response = self.client.post(f'/api/v1/communications/{conv.pk}/at-counter/')
        self.assertEqual(response.status_code, 200)
        conv.refresh_from_db()
        self.assertTrue(counter.in_visit(conv))
        self.assertTrue(conv.messages.filter(is_internal_note=True, body__icontains='at the counter').exists())


class BatchAndCrossingTests(Base):

    def setUp(self):
        super().setUp()
        closed = patch(OPEN, return_value=False)
        closed.start()
        self.addCleanup(closed.stop)

    def test_after_a_batch_is_acknowledged_more_files_wait_for_words(self):
        photo = self.customer(file=True)
        AssistantRun.objects.create(conversation=self.conv, trigger=photo, mode='live',
                                    decision=AssistantRun.REPLIED)
        self.octos('Got your photo. How many copies?')
        model = Model(says(text('x')))
        run = self.respond(model, self.customer(file=True))
        self.assertEqual(model.calls, [])
        self.assertEqual(run.decision, AssistantRun.SKIPPED)

    def test_words_after_a_batch_go_to_octos(self):
        self.customer(file=True)
        self.octos('Got your photo. How many copies?')
        model = Model(says(text('Got it, 2 copies.')))
        self.respond(model, self.customer('2 copies, A4'))
        self.assertTrue(model.calls)

    def test_a_message_crossing_octos_reply_is_still_answered(self):
        # Mercy, 6 Nov: her photo landed while Octos was answering "Black and white".
        said = self.customer('Black and white')
        AssistantRun.objects.create(conversation=self.conv, trigger=said, mode='live',
                                    decision=AssistantRun.REPLIED)
        photo = self.customer(file=True)
        self.octos('Is it A4 or A3?')
        run = self.respond(Model(says(text('Got your photo. How many copies?'))), photo)
        self.assertEqual(run.decision, AssistantRun.REPLIED)

    def test_a_message_already_answered_is_not_answered_again(self):
        said = self.customer('Hello')
        AssistantRun.objects.create(conversation=self.conv, trigger=said, mode='live',
                                    decision=AssistantRun.REPLIED)
        run = self.respond(Model(says(text('x'))), said)
        self.assertEqual(run.decision, AssistantRun.SKIPPED)

    def test_a_fast_human_is_not_a_bot(self):
        self.octos('Is it A4 or A3?')
        self.customer('2 copies please')
        self.octos('Got it.')
        self.customer('A4')
        self.assertIsNone(brain._looks_automated(self.conv, timezone.now()))


class FilesTests(Base):

    def test_paper_sizes(self):
        self.assertEqual(whatsapp_media.paper_size(210, 297), 'A4')
        self.assertEqual(whatsapp_media.paper_size(420, 297), 'A3')
        self.assertEqual(whatsapp_media.paper_size(100, 100), '100 x 100 mm')

    def test_a_file_that_cant_be_measured_is_described_less(self):
        self.assertNotIn('paper', whatsapp_media.describe(b'not a picture', 'x.png', 'image/png'))

    def test_octos_sees_the_paper_size_and_colour(self):
        msg = Message.objects.create(
            conversation=self.conv, direction=Message.INBOUND, channel=Message.WHATSAPP,
            message_type=Message.DOCUMENT, body='cv.pdf', media_id='m-2', media_name='cv.pdf',
            media_pages=2, media_file='whatsapp/cv.pdf', media_info={'paper': 'A4', 'colour_mode': 'RGB'})
        said = str(brain._history(self.conv))
        self.assertIn('cv.pdf, 2 pages, A4, colour', said)
        self.assertIn(f'file {msg.pk}', said)


class NameOncePerVisitTests(Base):

    def setUp(self):
        super().setUp()
        from apps.customers.models.customer import CustomerProfile
        self.conv.customer = CustomerProfile.objects.create(
            first_name='James', last_name='Adjei', phone='+233244999001', customer_type='INDIVIDUAL')
        self.conv.save(update_fields=['customer'])

    def test_a_new_visit_greets_by_name(self):
        self.assertIn('Greet them by name once', prompt.system_prompt(self.conv, [])[1]['text'])

    def test_within_a_visit_the_name_is_not_used_again(self):
        self.octos('Good afternoon, James! How can I help?')
        self.assertIn('already greeted', prompt.system_prompt(self.conv, [])[1]['text'])



class JamesTests(Base):
    """James, 6 Nov 2026: 'I want 3 copies of this file', the PDF 12 seconds behind."""

    def setUp(self):
        super().setUp()
        closed = patch(OPEN, return_value=False)
        closed.start()
        self.addCleanup(closed.stop)

    def test_words_promising_a_file_wait_for_it(self):
        self.assertEqual(counter.quiet_window(self.customer('I want 3 copies of this file')), counter.CLOSED_WAIT)

    def test_words_after_the_file_has_come_wait_briefly(self):
        self.customer(file=True)
        self.assertEqual(counter.quiet_window(self.customer('3 copies of this please')), counter.WORDS_WAIT)

    def test_ordinary_words_wait_briefly(self):
        self.assertEqual(counter.quiet_window(self.customer('How much is A4 colour?')), counter.WORDS_WAIT)

    def test_a_reply_that_crossed_the_files_does_not_silence_the_next_one(self):
        words = self.customer('I want 3 copies of this file')
        AssistantRun.objects.create(conversation=self.conv, trigger=words, mode='live',
                                    decision=AssistantRun.REPLIED)
        self.customer(file=True)
        self.octos("The file didn't come through on my side. Could you send it again?")
        again = self.customer(file=True)
        model = Model(says(text('Got it, 3 pages. Colour or black and white?')))
        run = self.respond(model, again)
        self.assertTrue(model.calls)
        self.assertEqual(run.decision, AssistantRun.REPLIED)
