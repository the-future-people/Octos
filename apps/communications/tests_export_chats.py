"""export_chats: one day's chats in a file for review (17 Nov 2026)."""
from datetime import datetime, time, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.communications.models import AssistantRun, Message
from apps.communications.tests import make_conversation

IN_MEMORY = {
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(STORAGES=IN_MEMORY)
class ExportChatsTests(TestCase):

    def setUp(self):
        self.day = timezone.localdate() - timedelta(days=1)
        noon = timezone.make_aware(datetime.combine(self.day, time(12, 0)))
        self.chat = make_conversation(None, contact_name='Ama', contact_phone='+233244001234')
        asked = Message.objects.create(conversation=self.chat, direction=Message.INBOUND, channel=Message.WHATSAPP,
                                       body='How much for 20 copies?')
        said = Message.objects.create(conversation=self.chat, direction=Message.OUTBOUND, channel=Message.WHATSAPP,
                                      body="That's GHS 10.00.")
        Message.objects.filter(pk=asked.pk).update(created_at=noon)
        Message.objects.filter(pk=said.pk).update(created_at=noon + timedelta(seconds=20))
        run = AssistantRun.objects.create(conversation=self.chat, trigger=asked, mode='live', decision='REPLIED',
                                          reply="That's GHS 10.00.", tool_calls=[
                                              {'name': 'quote', 'input': {'copies': 20}, 'result': {'total': '10.00'}}])
        AssistantRun.objects.filter(pk=run.pk).update(created_at=noon + timedelta(seconds=15))

    def export(self, *args):
        out = StringIO()
        call_command('export_chats', '--print', *args, stdout=out)
        return out.getvalue()

    def test_yesterday_by_default_with_octos_runs_and_tools(self):
        text = self.export()
        self.assertIn('## 1. Ama (…1234)', text)
        self.assertIn('Customer: How much for 20 copies?', text)
        self.assertIn('⚙ Octos replied', text)
        self.assertIn('tool quote', text)
        self.assertIn('Octos: That', text)
        self.assertNotIn('233244001234', text)
        self.assertIn('1 chats exported to exports/chats-', text)

    def test_another_day_has_none(self):
        text = self.export('--date', (self.day - timedelta(days=3)).isoformat())
        self.assertIn('0 chats exported', text)
