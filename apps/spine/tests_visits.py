"""
Visits: one customer, one sitting (Layer 1, Step 1.2).
Run: docker compose run --rm web python manage.py test apps.spine.tests_visits -v 2
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.communications.models import Conversation
from apps.spine import kinds
from apps.spine.models import Event, Visit
from apps.spine.recorder import record
from apps.spine.visits import close_quiet

T0 = timezone.now() - timedelta(days=1)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


class VisitTests(TestCase):
    def setUp(self):
        self.chat = Conversation.objects.create(
            branch=None, contact_phone='+233244123456', channel=Conversation.WHATSAPP)

    def say(self, minutes, kind=kinds.MESSAGE_RECEIVED, **extra):
        event, _ = record(kind, actor=Event.CUSTOMER, conversation=self.chat,
                          occurred_at=at(minutes), **extra)
        event.refresh_from_db()
        return event

    def test_a_customers_message_opens_a_visit(self):
        event = self.say(0)
        visit = Visit.objects.get()
        self.assertEqual(event.visit, visit)
        self.assertIsNone(visit.closed_at)
        self.assertEqual(visit.opened_at, at(0))

    def test_messages_within_two_hours_share_the_visit(self):
        first = self.say(0)
        second = self.say(90)
        self.assertEqual(first.visit, second.visit)
        self.assertEqual(Visit.objects.get().last_activity_at, at(90))

    def test_after_two_quiet_hours_the_next_message_is_a_new_visit(self):
        first = self.say(0)
        second = self.say(150)
        self.assertNotEqual(first.visit, second.visit)
        old = Visit.objects.get(pk=first.visit_id)
        self.assertEqual(old.outcome, 'NO_ACTION')
        self.assertTrue(old.timed_out)
        self.assertEqual(old.closed_at, at(120))      # backdated to when it went quiet

    def test_a_delivery_receipt_never_opens_a_visit(self):
        self.say(0, kind=kinds.MESSAGE_DELIVERED)
        self.assertFalse(Visit.objects.exists())

    def test_a_receipt_does_not_keep_a_visit_alive(self):
        self.say(0)
        self.say(100, kind=kinds.MESSAGE_DELIVERED)
        self.assertEqual(Visit.objects.get().last_activity_at, at(0))

    def test_an_outcome_closes_the_visit_and_points_at_its_proof(self):
        self.say(0)
        created = self.say(5, kind=kinds.JOB_CREATED)
        visit = Visit.objects.get()
        self.assertEqual(visit.outcome, 'JOB_CREATED')
        self.assertFalse(visit.timed_out)
        self.assertEqual(visit.closed_by_event, created)
        self.assertTrue(Event.objects.filter(kind=kinds.VISIT_CLOSED, visit=visit).exists())

    def test_after_an_outcome_the_next_message_opens_a_new_visit(self):
        self.say(0)
        self.say(5, kind=kinds.CONVERSATION_RESOLVED)
        self.say(10)
        self.assertEqual(Visit.objects.count(), 2)

    def test_the_sweep_closes_quiet_visits(self):
        self.say(0)
        self.assertEqual(close_quiet(now=at(200)), 1)
        visit = Visit.objects.get()
        self.assertEqual(visit.outcome, 'NO_ACTION')
        self.assertEqual(visit.closed_at, at(120))

    def test_a_visit_left_after_a_payment_link_is_abandoned(self):
        self.say(0)
        self.say(3, kind=kinds.PAYMENT_LINK_SENT)
        close_quiet(now=at(300))
        self.assertEqual(Visit.objects.get().outcome, 'ABANDONED')

    def test_a_repeated_event_changes_no_visit(self):
        record(kinds.MESSAGE_RECEIVED, conversation=self.chat, occurred_at=at(0), key='wa:same')
        record(kinds.MESSAGE_RECEIVED, conversation=self.chat, occurred_at=at(500), key='wa:same')
        visit = Visit.objects.get()
        self.assertEqual(visit.last_activity_at, at(0))
        self.assertIsNone(visit.closed_at)

    def test_only_one_open_visit_per_conversation(self):
        self.say(0)
        self.say(1)
        self.assertEqual(Visit.objects.filter(closed_at__isnull=True).count(), 1)
