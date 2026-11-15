"""
When "a person has this chat open" may keep Octos quiet (15 Nov 2026).

Kingsford, 9pm Sunday: a file after "ignore that one, use a different one"
got nothing, "a person has this chat open". It was Khofi, watching from
home, with the shop shut. Now: outside opening hours the chat being open
never silences Octos; only a real open counts, never the inbox reloading an
open chat by itself; and a file the customer has just said what to do with
is answered, not met with the stock question.

Run: docker compose exec web python manage.py test apps.communications.tests_focus -t . --noinput
"""
from unittest.mock import patch

from django.core.cache import cache

from apps.communications.assistant import counter
from apps.communications.models import AssistantRun
from apps.communications.services import opened
from apps.communications.tests import CommunicationsTestBase, make_conversation
from apps.communications.tests_assistant_brain import Model, says, text
from apps.communications.tests_octos_update import OPEN, Base


class FocusTests(Base):

    def focus(self):
        cache.set(opened._focus_key(self.conv.pk), True, opened.FOCUS_SECONDS)
        self.addCleanup(cache.delete, opened._focus_key(self.conv.pk))

    def test_shop_closed_an_open_chat_does_not_silence_octos(self):
        self.focus()
        self.customer('Ignore that one, use a different one')
        model = Model(says(text("Got it, I'll use this one. Shall I go ahead?")))
        with patch(OPEN, return_value=False):
            run = self.respond(model, self.customer(file=True))
        self.assertTrue(model.calls)
        self.assertEqual(run.decision, AssistantRun.REPLIED)

    def test_shop_open_an_open_chat_still_keeps_octos_quiet(self):
        self.focus()
        with patch(OPEN, return_value=True):
            run = self.respond(Model(says(text('x'))), self.customer(file=True))
        self.assertEqual(run.decision, AssistantRun.SKIPPED)

    def test_shop_open_a_file_after_saying_what_for_is_answered(self):
        self.customer('Ignore that one, use a different one')
        model = Model(says(text("Got it, I'll use this one. Shall I go ahead?")))
        with patch(OPEN, return_value=True):
            self.respond(model, self.customer(file=True))
        self.assertTrue(model.calls)
        self.assertFalse(self.sent().filter(body=counter.FORK_TEXT).exists())


class RealOpensOnlyTests(CommunicationsTestBase):

    def test_the_inbox_reloading_an_open_chat_is_not_a_person_looking(self):
        conv = make_conversation(self.branch, contact_phone='+233244000614')
        cache.delete(opened._focus_key(conv.pk))
        self.client.get(f'/api/v1/communications/{conv.pk}/', {'after': 999999})
        self.assertFalse(opened.in_focus(conv.pk))
        self.client.get(f'/api/v1/communications/{conv.pk}/')
        self.assertTrue(opened.in_focus(conv.pk))
        cache.delete(opened._focus_key(conv.pk))
