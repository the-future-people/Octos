"""
Fixes from reading the 16 Nov 2026 chats, one class each:

  goodbyes      "Thank you too" after a receipt only closes the chat
  dealt with    a file already made into a job is marked so in what Octos reads
  albums        WhatsApp's album cover is shown, never answered or read
  after hours   a file sent while closed gets the opening time and the question
  quiet remote  a customer who sent a file from afar and went quiet goes to Needs you
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.communications.assistant import brain, counter
from apps.communications.models import Conversation, Message
from apps.communications.services import whatsapp_inbound
from apps.communications.services.quiet_remote import flag_quiet
from apps.communications.tests import make_conversation, make_job, make_org
from apps.spine import kinds
from apps.spine.models import Event, Visit
from apps.spine.recorder import record


class GoodbyeTests(TestCase):

    def test_longer_goodbyes(self):
        for text in ('thank you too', 'thanks boss', 'ok thank you so much', 'well received, god bless',
                     'thank you very much sir', 'noted with thanks', 'appreciated'):
            self.assertTrue(brain._goodbye(text), text)

    def test_not_goodbyes(self):
        for text in ('yes please', 'ok i want 3 copies', 'thank you, can you print it', 'how much', 'you',
                     'good', 'same to you can you call me'):
            self.assertFalse(brain._goodbye(text), text)


class DealtWithTests(TestCase):

    def setUp(self):
        self.branch = make_org('-DW')
        self.chat = make_conversation(None, contact_phone='+233244880001')

    def file(self, name, ago):
        m = Message.objects.create(conversation=self.chat, direction=Message.INBOUND, channel=Message.WHATSAPP,
                                   message_type=Message.DOCUMENT, media_id=f'm-{name}', media_name=name, media_pages=3)
        Message.objects.filter(pk=m.pk).update(created_at=timezone.now() - ago)

    def read(self):
        return '\n'.join(t['content'] for t in brain._history(self.chat))

    def line(self, text, name):
        return next(line for line in text.splitlines() if name in line)

    def test_a_file_before_its_job_is_marked_dealt_with(self):
        self.file('portfolio.pdf', timedelta(minutes=20))
        job = make_job(self.branch)
        self.chat.jobs.add(job)
        Message.objects.create(conversation=self.chat, direction=Message.INBOUND, channel=Message.WHATSAPP,
                               body='Thank you too')
        self.assertIn('already dealt with', self.line(self.read(), 'portfolio.pdf'))

    def test_a_file_after_the_job_is_not(self):
        job = make_job(self.branch)
        self.chat.jobs.add(job)
        from apps.jobs.models import Job
        Job.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(minutes=30))
        self.file('new.pdf', timedelta(minutes=5))
        Message.objects.create(conversation=self.chat, direction=Message.INBOUND, channel=Message.WHATSAPP, body='Price?')
        self.assertNotIn('already dealt with', self.line(self.read(), 'new.pdf'))


class AlbumCoverTests(TestCase):

    def setUp(self):
        make_org('-AL')

    def test_shown_with_plain_words(self):
        self.assertEqual(whatsapp_inbound._content({'type': 'unsupported'})[1], whatsapp_inbound.ALBUM_NOTE)

    @patch('apps.communications.services.whatsapp_inbound.wake_octos')
    def test_kept_but_never_wakes_octos(self, wake):
        whatsapp_inbound._receive({'id': 'wamid.album1', 'from': '233244880002', 'type': 'unsupported'}, 'Ama')
        message = Message.objects.get(external_id='wamid.album1')
        self.assertEqual(message.kind, Message.UNSUPPORTED)
        wake.assert_not_called()

    def test_left_out_of_what_octos_reads(self):
        chat = make_conversation(None, contact_phone='+233244880003')
        Message.objects.create(conversation=chat, direction=Message.INBOUND, channel=Message.WHATSAPP,
                               kind=Message.UNSUPPORTED, body=whatsapp_inbound.ALBUM_NOTE)
        Message.objects.create(conversation=chat, direction=Message.INBOUND, channel=Message.WHATSAPP, body='Hello')
        everything = '\n'.join(t['content'] for t in brain._history(chat))
        self.assertNotIn('album', everything.lower())


class AfterHoursFileTests(TestCase):

    def setUp(self):
        branch = make_org('-AH')
        branch.is_trading = True
        branch.save()

    @patch('apps.communications.assistant.tools.branch_hours', return_value={'next_opening': '8:00am tomorrow'})
    def test_says_when_we_open_and_asks(self, _hours):
        text = counter.closed_fork_text(timezone.now())
        self.assertIn("We're closed now and open again at 8:00am tomorrow.", text)
        self.assertIn('What would you like done with it?', text)


class QuietRemoteTests(TestCase):

    def setUp(self):
        self.branch = make_org('-QR')
        self.chat = make_conversation(None, contact_phone='+233244880004')
        self.now = timezone.now()
        p = patch('apps.communications.assistant.counter.shop_open', return_value=True)
        p.start()
        self.addCleanup(p.stop)
        alerts = patch('apps.notifications.services.notify_many')
        alerts.start()
        self.addCleanup(alerts.stop)

    def sent_file(self, minutes_ago):
        record(kinds.MESSAGE_RECEIVED, actor=Event.CUSTOMER, conversation=self.chat,
               occurred_at=self.now - timedelta(minutes=minutes_ago), key=f'wa:qr-{minutes_ago}',
               payload={'has_file': True})
        return Visit.objects.get(conversation=self.chat, closed_at__isnull=True)

    def test_a_quiet_remote_file_goes_to_needs_you_once(self):
        self.sent_file(40)
        self.assertEqual(flag_quiet(self.now), 1)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.handled_by, Conversation.STAFF)
        self.assertIn('went quiet', self.chat.handoff_reason)
        self.assertEqual(flag_quiet(self.now), 0)

    def test_not_yet_quiet_long_enough(self):
        self.sent_file(10)
        self.assertEqual(flag_quiet(self.now), 0)

    def test_a_job_made_means_nothing_to_chase(self):
        visit = self.sent_file(40)
        Event.objects.create(kind=kinds.JOB_LINKED, conversation=self.chat, visit=visit,
                             occurred_at=self.now - timedelta(minutes=38))
        self.assertEqual(flag_quiet(self.now), 0)

    def test_a_job_attached_by_hand_counts(self):
        self.sent_file(40)
        self.chat.jobs.add(make_job(self.branch))       # no event, as from the Railway shell
        self.assertEqual(flag_quiet(self.now), 0)

    def test_a_receipt_sent_counts(self):
        self.sent_file(40)
        Message.objects.create(conversation=self.chat, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
                               kind='receipt', body="Here's your receipt.")
        self.assertEqual(flag_quiet(self.now), 0)

    def test_at_the_counter_the_attendant_has_them(self):
        visit = self.sent_file(40)
        Visit.objects.filter(pk=visit.pk).update(presence=Visit.AT_COUNTER)
        self.assertEqual(flag_quiet(self.now), 0)

    def test_closed_shop_flags_nothing(self):
        self.sent_file(40)
        with patch('apps.communications.assistant.counter.shop_open', return_value=False):
            self.assertEqual(flag_quiet(self.now), 0)
