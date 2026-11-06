"""
The brain, with the model replaced by a scripted stand-in: no test calls
Anthropic or costs anything. Each test scripts what the "model" says and
checks what Octos does with it: silence, the guards, tools, the checker,
shadow notes, live sends, handovers and failures.
"""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from django.utils import timezone
from django.test import TestCase, override_settings

from apps.communications.assistant import brain
from apps.communications.models import AssistantRun, Conversation, Message
from apps.communications.tests import make_conversation, make_org
from apps.communications.tests_whatsapp_outbound import customer_wrote

PHONE = '+233244777001'
HOURS = {'branch': 'Westland', 'open_now': True,
         'today': {'opens': '8:00am', 'closes': '7:30pm'}, 'next_opening': '8:00am tomorrow'}


def text(t):
    return SimpleNamespace(type='text', text=t)


def tool(name, args, id='t1'):
    return SimpleNamespace(type='tool_use', name=name, input=args, id=id)


def says(*blocks, stop='end_turn'):
    return SimpleNamespace(stop_reason=stop, content=list(blocks),
                           usage=SimpleNamespace(input_tokens=100, output_tokens=20))


class Model:
    """Stands in for anthropic.Anthropic(...): returns the scripted responses in order."""

    def __init__(self, *responses, error=None):
        self.responses, self.error, self.calls = list(responses), error, []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.responses.pop(0)


@override_settings(ANTHROPIC_API_KEY='test-key', OCTOS_ASSISTANT_MODE='live')
class BrainTests(TestCase):

    def setUp(self):
        branch = make_org()
        branch.is_trading = True
        branch.save()
        self.conv = make_conversation(None, contact_phone=PHONE)
        self.asked = customer_wrote(self.conv, timedelta(seconds=30))
        alerts = patch('apps.notifications.services.notify_many')
        alerts.start()
        self.addCleanup(alerts.stop)

    def run_with(self, model, trigger=None):
        with patch('anthropic.Anthropic', return_value=model):
            return brain.respond(self.conv.pk, (trigger or self.asked).pk)

    def sent(self):
        return self.conv.messages.filter(direction=Message.OUTBOUND, is_internal_note=False)

    # ── Off and silent ──────────────────────────────────────────

    @override_settings(OCTOS_ASSISTANT_MODE='off')
    def test_off_does_nothing_and_records_nothing(self):
        model = Model(says(text('Hello')))
        self.assertIsNone(self.run_with(model))
        self.assertEqual(model.calls, [])
        self.assertFalse(AssistantRun.objects.exists())

    def test_silent_when_a_person_has_the_conversation(self):
        Conversation.objects.filter(pk=self.conv.pk).update(handled_by=Conversation.STAFF)
        model = Model(says(text('Hello')))
        run = self.run_with(model)
        self.assertEqual((run.decision, run.reason), (AssistantRun.SKIPPED, 'a person has taken over this conversation'))
        self.assertEqual(model.calls, [])

    def test_only_the_latest_message_is_answered(self):
        customer_wrote(self.conv, timedelta(seconds=5))  # a newer message arrived
        run = self.run_with(Model(says(text('Hello'))))
        self.assertEqual(run.decision, AssistantRun.SKIPPED)
        self.assertIn('newer message', run.reason)

    def test_an_auto_reply_to_octos_is_ignored(self):
        octos = Message.objects.create(conversation=self.conv, direction=Message.OUTBOUND,
                                       channel=Message.WHATSAPP, body='Octos here 👋')
        echo = customer_wrote(self.conv, timedelta(seconds=0))
        Message.objects.filter(pk=echo.pk).update(created_at=octos.created_at + timedelta(seconds=2))
        run = self.run_with(Model(says(text('Hello'))), trigger=echo)
        self.assertEqual(run.decision, AssistantRun.SKIPPED)
        self.assertIn('automatic reply', run.reason)

    # ── Answering ───────────────────────────────────────────────

    def test_live_sends_the_reply_as_octos(self):
        run = self.run_with(Model(says(text("Good evening 👋 Octos here, Farhat's assistant. How can I help?"))))
        self.assertEqual(run.decision, AssistantRun.REPLIED)
        reply = self.sent().get()
        self.assertIsNone(reply.sent_by)
        self.assertEqual(run.sent, reply)
        self.assertEqual((run.input_tokens, run.output_tokens), (100, 20))

    @override_settings(OCTOS_ASSISTANT_MODE='shadow')
    def test_shadow_writes_a_note_and_sends_nothing(self):
        run = self.run_with(Model(says(text('Good evening 👋 How can I help?'))))
        self.assertEqual(run.decision, AssistantRun.SHADOWED)
        self.assertFalse(self.sent().exists())
        note = self.conv.messages.get(is_internal_note=True)
        self.assertTrue(note.body.startswith('Octos would say: Good evening'))

    @patch('apps.communications.assistant.tools.branch_hours', return_value=HOURS)
    def test_a_lookup_then_an_answer_from_it(self, hours):
        model = Model(
            says(tool('branch_hours', {}), stop='tool_use'),
            says(text("Yes, we're open till 7:30pm today 😊")),
        )
        run = self.run_with(model)
        self.assertEqual(run.decision, AssistantRun.REPLIED)
        self.assertEqual(run.tool_calls[0]['name'], 'branch_hours')
        # The second call carried the tool's result back to the model.
        self.assertEqual(model.calls[1]['messages'][-1]['content'][0]['type'], 'tool_result')

    @patch('apps.communications.assistant.tools.customer_jobs', return_value={'found': False, 'jobs': []})
    def test_jobs_are_always_looked_up_for_the_number_writing(self, jobs):
        model = Model(
            says(tool('customer_jobs', {'phone': '+233200000999'}), stop='tool_use'),
            says(text("I can't find an open job under this number.")),
        )
        self.run_with(model)
        jobs.assert_called_once_with(PHONE)

    # ── Safety ──────────────────────────────────────────────────

    def test_a_price_nobody_looked_up_is_blocked_and_a_person_brought_in(self):
        run = self.run_with(Model(says(text("That's GHS 35 for the lot."))))
        self.assertEqual(run.decision, AssistantRun.BLOCKED)
        self.assertIn('GHS 35.00', run.reason)
        # The made-up price never goes out; a holding reply with no figures does.
        self.assertIn(self.sent().get().body, (brain.HOLDING, brain.HOLDING_CLOSED))
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.handled_by, Conversation.STAFF)

    def test_asking_for_a_person_sends_the_reply_and_hands_over(self):
        model = Model(
            says(tool('hand_to_person', {'reason': 'customer asked to be called'}), stop='tool_use'),
            says(text('Sure, someone from the team will call you shortly 🙏')),
        )
        run = self.run_with(model)
        self.assertEqual(run.decision, AssistantRun.HANDED_OVER)
        self.assertTrue(self.sent().exists())
        self.conv.refresh_from_db()
        self.assertEqual((self.conv.handled_by, self.conv.handoff_reason),
                         (Conversation.STAFF, 'customer asked to be called'))

    def test_a_failure_hands_the_customer_to_a_person(self):
        run = self.run_with(Model(error=RuntimeError('API down')))
        self.assertEqual(run.decision, AssistantRun.FAILED)
        self.assertIn('API down', run.error)
        self.assertIn(self.sent().get().body, (brain.HOLDING, brain.HOLDING_CLOSED))

    def test_a_reply_cut_off_mid_sentence_is_never_sent(self):
        run = self.run_with(Model(says(text('For 5 sets of A3 colour, one side, 10 p'), stop='max_tokens')))
        self.assertEqual(run.decision, AssistantRun.FAILED)
        # The half sentence never goes out; the holding reply does.
        self.assertIn(self.sent().get().body, (brain.HOLDING, brain.HOLDING_CLOSED))
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.handled_by, Conversation.STAFF)

    # ── What the model reads ────────────────────────────────────

    def test_the_conversation_starts_with_the_customer_and_merges_turns(self):
        customer_wrote(self.conv, timedelta(seconds=20))
        turns = brain._history(self.conv)
        self.assertEqual(turns[0]['role'], 'user')
        self.assertEqual(len(turns), 1)  # two customer messages, one turn

    
    def test_octos_keeps_answering_while_waiting_for_a_person(self):
        Conversation.objects.filter(pk=self.conv.pk).update(
            handled_by=Conversation.STAFF, handoff_reason='customer asked to be called')
        model = Model(says(text("You're welcome! Someone from the team will call you.")))
        run = self.run_with(model)
        self.assertEqual(run.decision, AssistantRun.REPLIED)
        self.assertIn('already been asked to follow up', model.calls[0]['system'][1]['text'])


    def octos_then_customer(self, octos_said, customer_said):
        """
        Octos speaks 20 seconds ago, the customer answers now. After setUp's
        own message (30 seconds ago), so Octos's really is the one just
        before; and more than 5 seconds apart, so no auto-reply guard.
        """
        said = Message.objects.create(conversation=self.conv, direction=Message.OUTBOUND,
                                      channel=Message.WHATSAPP, body=octos_said)
        Message.objects.filter(pk=said.pk).update(created_at=timezone.now() - timedelta(seconds=20))
        answer = customer_wrote(self.conv, timedelta(seconds=0))
        Message.objects.filter(pk=answer.pk).update(body=customer_said)
        return answer

    def test_ok_after_a_statement_ends_the_conversation(self):
        ok = self.octos_then_customer('Your print starts once you have paid.', 'Okay')
        model = Model(says(text('Good night!')))
        run = self.run_with(model, trigger=ok)
        self.assertEqual((run.decision, run.reason),
                         (AssistantRun.SKIPPED, 'the customer was only closing the conversation'))
        self.assertEqual(model.calls, [])

    def test_ok_after_octos_asked_is_an_answer(self):
        ok = self.octos_then_customer('Shall I send the payment link?', 'Ok')
        run = self.run_with(Model(says(text('Here you go.'))), trigger=ok)
        self.assertEqual(run.decision, AssistantRun.REPLIED, run.reason)