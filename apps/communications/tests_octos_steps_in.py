"""
Two Octos fixes from 17 Nov 2026, with the model scripted (no API calls).

1. A person who steps in while Octos is writing wins: Octos looks again just
   before sending, and stays quiet if a person took over or replied, or if the
   customer wrote again (that newer message gets its own answer).
2. A file from an earlier visit is marked as such, so it isn't priced together
   with today's.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.communications.assistant import brain
from apps.communications.models import AssistantRun, Conversation, Message
from apps.communications.tests import make_conversation, make_org
from apps.communications.tests_assistant_brain import Model, says, text
from apps.communications.tests_whatsapp_outbound import customer_wrote


class Meddling(Model):
    """The scripted model, plus something that happens while it 'thinks'."""

    def __init__(self, meanwhile, *responses):
        super().__init__(*responses)
        self.meanwhile = meanwhile

    def create(self, **kwargs):
        self.meanwhile()
        return super().create(**kwargs)


@override_settings(ANTHROPIC_API_KEY='test-key', OCTOS_ASSISTANT_MODE='live')
class SteppingInTests(TestCase):

    def setUp(self):
        branch = make_org('-SI')
        branch.is_trading = True
        branch.save()
        self.conv = make_conversation(None, contact_phone='+233244777901')
        self.asked = customer_wrote(self.conv, timedelta(seconds=30))
        self.person = CustomUser.objects.create(employee_id='SI-1', first_name='Esi', last_name='Test',
                                                email='si-1@test.local', branch=branch)
        for target, value in (('apps.notifications.services.notify_many', None),
                              ('apps.communications.assistant.counter.shop_open', False)):
            p = patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def run_with(self, meanwhile):
        model = Meddling(meanwhile, says(text('Sure, send me the file and I will check it.')))
        with patch('anthropic.Anthropic', return_value=model):
            return brain.respond(self.conv.pk, self.asked.pk)

    def octos_sent(self):
        return self.conv.messages.filter(direction=Message.OUTBOUND, sent_by__isnull=True, is_internal_note=False)

    def test_a_person_takes_over_while_octos_writes(self):
        def take_over():
            Conversation.objects.filter(pk=self.conv.pk).update(handled_by=Conversation.STAFF, handoff_reason='')
        run = self.run_with(take_over)
        self.assertEqual(run.decision, AssistantRun.SKIPPED)
        self.assertIn('took over', run.reason)
        self.assertFalse(self.octos_sent().exists())

    def test_a_person_replies_while_octos_writes(self):
        def reply():
            Message.objects.create(conversation=self.conv, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
                                   body="I'll help you, one moment.", sent_by=self.person)
        run = self.run_with(reply)
        self.assertEqual(run.decision, AssistantRun.SKIPPED)
        self.assertIn('replied', run.reason)
        self.assertFalse(self.octos_sent().exists())

    def test_the_customer_writes_again_while_octos_writes(self):
        def again():
            Message.objects.create(conversation=self.conv, direction=Message.INBOUND, channel=Message.WHATSAPP,
                                   body='Actually make it 30 copies')
        run = self.run_with(again)
        self.assertEqual(run.decision, AssistantRun.SKIPPED)
        self.assertFalse(self.octos_sent().exists())

    def test_nobody_steps_in_and_octos_replies(self):
        run = self.run_with(lambda: None)
        self.assertEqual(run.decision, AssistantRun.REPLIED)
        self.assertTrue(self.octos_sent().exists())


class EarlierVisitFilesTests(TestCase):

    def setUp(self):
        self.conv = make_conversation(None, contact_phone='+233244777902')

    def file(self, name, pages, ago):
        m = Message.objects.create(conversation=self.conv, direction=Message.INBOUND, channel=Message.WHATSAPP,
                                   message_type=Message.DOCUMENT, media_id=f'media-{name}', media_name=name,
                                   media_pages=pages)
        Message.objects.filter(pk=m.pk).update(created_at=timezone.now() - ago)
        return m

    def said(self, body, ago):
        m = Message.objects.create(conversation=self.conv, direction=Message.INBOUND, channel=Message.WHATSAPP, body=body)
        Message.objects.filter(pk=m.pk).update(created_at=timezone.now() - ago)

    def test_yesterdays_file_is_marked_and_todays_is_not(self):
        self.file('old-flyer.pdf', 4, timedelta(hours=20))
        self.file('new-cv.pdf', 2, timedelta(minutes=5))
        self.said('How much for these?', timedelta(minutes=4))
        turns = brain._history(self.conv)
        everything = '\n'.join(t['content'] for t in turns)
        old_line = next(line for line in everything.splitlines() if 'old-flyer.pdf' in line)
        new_line = next(line for line in everything.splitlines() if 'new-cv.pdf' in line)
        self.assertIn('earlier visit', old_line)
        self.assertNotIn('earlier visit', new_line)
        self.assertIn('A new visit began', everything)

    def test_one_visit_has_no_marks(self):
        self.file('a.pdf', 1, timedelta(minutes=30))
        self.file('b.pdf', 1, timedelta(minutes=10))
        everything = '\n'.join(t['content'] for t in brain._history(self.conv))
        self.assertNotIn('earlier visit', everything)
        self.assertNotIn('A new visit began', everything)
