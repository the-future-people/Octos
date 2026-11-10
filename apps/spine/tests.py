"""
The spine's rules, proved (Layer 1, Step 1.1).
Run: docker compose run --rm web python manage.py test apps.spine.tests -v 2
"""
from django.test import TestCase

from apps.spine import kinds
from apps.spine.models import Event
from apps.spine.recorder import UnknownEventKind, record


class RecordTests(TestCase):
    def test_records_an_event(self):
        event, created = record(kinds.MESSAGE_RECEIVED, actor=Event.CUSTOMER,
                                payload={'text': 'Hi'}, reason='customer wrote in')
        self.assertTrue(created)
        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(event.kind, 'message.received')
        self.assertEqual(event.payload, {'text': 'Hi'})

    def test_same_key_is_recorded_once(self):
        # A webhook delivered twice must not create two events
        first, created_first = record(kinds.MESSAGE_RECEIVED, key='wa:wamid.ABC')
        second, created_second = record(kinds.MESSAGE_RECEIVED, key='wa:wamid.ABC')
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Event.objects.count(), 1)

    def test_events_without_keys_are_all_kept(self):
        record(kinds.OCTOS_STAYED_SILENT)
        record(kinds.OCTOS_STAYED_SILENT)
        self.assertEqual(Event.objects.count(), 2)

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(UnknownEventKind):
            record('message.recieved')          # the typo the vocabulary exists to catch
        self.assertFalse(Event.objects.exists())

    def test_events_cannot_be_edited(self):
        event, _ = record(kinds.JOB_CREATED)
        event.reason = 'rewriting history'
        with self.assertRaises(ValueError):
            event.save()

    def test_events_cannot_be_deleted(self):
        event, _ = record(kinds.JOB_CREATED)
        with self.assertRaises(ValueError):
            event.delete()
        self.assertEqual(Event.objects.count(), 1)

    def test_every_kind_is_noun_dot_past_tense_style(self):
        for kind in kinds.ALL:
            self.assertRegex(kind, r'^[a-z]+\.[a-z_]+$', kind)
