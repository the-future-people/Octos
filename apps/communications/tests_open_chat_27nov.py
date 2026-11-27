"""
A chat open on a screen, and files deleted at the customer's word (27 Nov 2026).

Gifty sent six files and Moro "Hi" and his ticket while someone had their
chats open: Octos stood down for good ("a person has this chat open") and
they heard nothing for ten minutes. Now an open chat holds Octos for 3
minutes from the message; if nobody has written to them by then, Octos
answers as usual.

Lorrey's file never arrived; she asked for her files deleted. A later fetch
must never store it again.

Run: docker compose run --rm web python manage.py test apps.communications.tests_open_chat_27nov -t .
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from apps.communications.assistant import brain
from apps.communications.models import AssistantRun, Message
from apps.communications.services import customer_files, opened, whatsapp_media
from apps.communications.tests_assistant_brain import Model, says, text
from apps.communications.tests_octos_update import OPEN, Base


class AnOpenChatHoldsOctosTests(Base):

    def setUp(self):
        super().setUp()
        cache.set(opened._focus_key(self.conv.pk), True, opened.FOCUS_SECONDS)
        self.addCleanup(cache.delete, opened._focus_key(self.conv.pk))

    def aged(self, message, minutes):
        Message.objects.filter(pk=message.pk).update(created_at=timezone.now() - timedelta(minutes=minutes))
        message.refresh_from_db()
        return message

    def test_files_nobody_answered_are_answered_after_the_wait(self):
        files = self.aged(self.customer(file=True), 4)
        model = Model(says(text('Got your file. What would you like done with it?')))
        with patch(OPEN, return_value=True):
            run = self.respond(model, files)
        self.assertIsNotNone(run)
        self.assertNotEqual(run.reason, 'a person has this chat open')
        self.assertEqual(run.decision, AssistantRun.REPLIED)

    def test_a_greeting_nobody_answered_is_answered_after_the_wait(self):
        hi = self.aged(self.customer('Hi 👋'), 4)
        with patch(OPEN, return_value=True):
            run = self.respond(Model(says(text('Hi! How can we help?'))), hi)
        self.assertEqual(run.decision, AssistantRun.REPLIED)

    def test_a_person_who_wrote_meanwhile_keeps_octos_out(self):
        files = self.aged(self.customer(file=True), 4)
        staff = get_user_model().objects.create_user(email='att@x.com', password='x')
        Message.objects.create(conversation=self.conv, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
                               body='Got them, printing now', sent_by=staff)
        model = Model(says(text('x')))
        with patch(OPEN, return_value=True):
            run = self.respond(model, files)
        self.assertEqual((run.decision, run.reason), (AssistantRun.SKIPPED, 'a person has answered'))
        self.assertFalse(model.calls)


class DeletedAtTheirWordTests(Base):

    def test_a_file_never_saved_is_never_fetched_after_they_asked(self):
        saved = self.customer(file=True)
        Message.objects.filter(pk=saved.pk).update(media_file='communications/media/t/a.jpg')
        lost = self.customer(file=True)
        boss = get_user_model().objects.create_user(email='bm@x.com', password='x')
        with patch.object(customer_files, 'may_delete', return_value=True), \
                patch.object(customer_files, 'open_job', return_value=None), \
                patch.object(customer_files, '_message_print', return_value='sha'), \
                patch.object(customer_files, '_gone'):
            customer_files.delete(self.conv, [saved], boss, 'asked')
        lost.refresh_from_db()
        self.assertIsNotNone(lost.file_deleted_at)
        with patch.object(whatsapp_media, 'download') as download:
            whatsapp_media.fetch(lost.pk)
        download.assert_not_called()

    def test_the_14_day_clean_up_leaves_unsaved_files_alone(self):
        lost = self.customer(file=True)
        customer_files.delete(self.conv, [], None, '')
        lost.refresh_from_db()
        self.assertIsNone(lost.file_deleted_at)
