"""
The end-of-day thank-you and the payment reminder (14 Nov 2026).

Run: docker compose exec web python manage.py test apps.storefront.tests_thanks_and_reminder -t .
"""
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.communications.models import Message
from apps.communications.tests import make_conversation, make_org
from apps.customers.models import CustomerProfile
from apps.jobs.models import Job
from apps.storefront.models import Lead, OnlineOrder
from apps.storefront.services import payment_reminder, thanks

PHONE = '+233244000594'


class Base(TestCase):

    def setUp(self):
        self.branch = make_org()
        self.branch.is_trading = True
        self.branch.save()
        self.conv = make_conversation(None, contact_phone=PHONE)
        alerts = patch('apps.notifications.services.notify_many')
        alerts.start()
        self.addCleanup(alerts.stop)

    def wrote(self, body='Hi', ago=timedelta(hours=4)):
        """The customer wrote this long ago: inside the 24-hour window, not mid-conversation."""
        message = Message.objects.create(conversation=self.conv, direction=Message.INBOUND,
                                         channel=Message.WHATSAPP, body=body)
        Message.objects.filter(pk=message.pk).update(created_at=timezone.now() - ago)
        return message

    def sent(self, kind):
        return self.conv.messages.filter(direction=Message.OUTBOUND, kind=kind)


class ThanksTests(Base):

    def setUp(self):
        super().setUp()
        self.customer = CustomerProfile.objects.create(
            first_name='Ama', phone=PHONE, customer_type='INDIVIDUAL')

    def job(self, paid=True, days_ago=0):
        job = Job.objects.create(
            branch=self.branch, job_type=Job.INSTANT, title='Photocopy', customer=self.customer,
            status=Job.PAID if paid else Job.PENDING_PAYMENT,
            payment_state=Job.Payment.SETTLED if paid else Job.Payment.UNPAID)
        if days_ago:
            Job.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        return job

    def test_a_first_timer_is_thanked_warmly_once(self):
        self.job()
        self.wrote()
        self.assertEqual(thanks.thank_branch(self.branch), 1)
        body = self.sent(thanks.KIND).get().body
        self.assertIn('Thank you for choosing', body)
        self.assertIn('Ama', body)
        self.assertEqual(thanks.thank_branch(self.branch), 0)      # once in 7 days

    def test_a_returning_customer_gets_the_short_message(self):
        self.job(days_ago=30)
        self.job()
        self.wrote()
        thanks.thank_branch(self.branch)
        self.assertTrue(self.sent(thanks.KIND).get().body.startswith('Thank you for coming back today, Ama!'))

    def test_anyone_still_owing_is_not_thanked(self):
        self.job()
        self.job(paid=False)
        self.wrote()
        self.assertEqual(thanks.thank_branch(self.branch), 0)

    def test_no_window_means_no_thanks(self):
        self.job()
        self.assertEqual(thanks.thank_branch(self.branch), 0)

    def test_a_customer_who_opted_out_is_not_thanked(self):
        self.job()
        self.wrote()
        self.conv.marketing_opt_out = True
        self.conv.save(update_fields=['marketing_opt_out'])
        self.assertEqual(thanks.thank_branch(self.branch), 0)

    def test_mid_conversation_waits_for_the_next_run(self):
        self.job()
        self.wrote(ago=timedelta(minutes=2))
        self.assertEqual(thanks.thank_branch(self.branch), 0)

    def test_due_in_the_half_hour_before_closing(self):
        self.branch.opening_time, self.branch.closing_time = time(8, 0), time(18, 0)
        self.branch.save()
        at = lambda day, hour, minute: timezone.make_aware(datetime(2026, 11, day, hour, minute))
        self.assertTrue(thanks.due(self.branch, at(11, 17, 40)))     # Wednesday
        self.assertFalse(thanks.due(self.branch, at(11, 17, 20)))
        self.assertFalse(thanks.due(self.branch, at(11, 18, 5)))
        self.assertFalse(thanks.due(self.branch, at(15, 17, 40)))    # Sunday


class PaymentReminderTests(Base):

    def setUp(self):
        super().setUp()
        lead = Lead.objects.create(phone=PHONE, first_name='Kofi')
        self.order = OnlineOrder.objects.create(
            lead=lead, branch=self.branch, status=OnlineOrder.Status.AWAITING_PAYMENT,
            total=Decimal('45.00'),
            line_items=[{'service_name': 'Sticker printing', 'quantity': 10,
                         'unit_price': '4.50', 'total': '45.00'}],
            notes=f'Taken by Octos on WhatsApp (conversation {self.conv.pk})')
        self.link_sent(hours=3)
        opened = patch('apps.organization.services.hours.is_open', return_value=True)
        opened.start()
        self.addCleanup(opened.stop)

    def link_sent(self, hours):
        OnlineOrder.objects.filter(pk=self.order.pk).update(
            updated_at=timezone.now() - timedelta(hours=hours))

    def test_an_unpaid_order_is_reminded_once(self):
        self.wrote(ago=timedelta(hours=4))
        self.assertEqual(payment_reminder.remind_all(), 1)
        body = self.sent(payment_reminder.KIND).get().body
        self.assertIn('Sticker printing', body)
        self.assertIn('GHS 45.00', body)
        self.assertIn('Just say yes', body)
        self.assertEqual(payment_reminder.remind_all(), 0)
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.payment_reminded_at)

    def test_not_before_two_hours(self):
        self.wrote(ago=timedelta(hours=4))
        self.link_sent(hours=1)
        self.assertEqual(payment_reminder.remind_all(), 0)

    def test_waits_while_the_branch_is_closed(self):
        self.wrote(ago=timedelta(hours=4))
        with patch('apps.organization.services.hours.is_open', return_value=False):
            self.assertEqual(payment_reminder.remind_all(), 0)
        self.assertEqual(payment_reminder.remind_all(), 1)          # at opening

    def test_a_paid_order_is_left_alone(self):
        self.wrote(ago=timedelta(hours=4))
        OnlineOrder.objects.filter(pk=self.order.pk).update(status=OnlineOrder.Status.PAID)
        self.assertEqual(payment_reminder.remind_all(), 0)

    def test_a_customer_who_said_no_is_left_alone(self):
        self.wrote('No thanks', ago=timedelta(hours=1))
        self.assertEqual(payment_reminder.remind_all(), 0)

    def test_pay_tomorrow_still_gets_the_reminder(self):
        self.wrote("I'll pay tomorrow", ago=timedelta(hours=1))
        self.assertEqual(payment_reminder.remind_all(), 1)

    def test_an_order_not_taken_on_whatsapp_is_left_alone(self):
        self.wrote(ago=timedelta(hours=4))
        OnlineOrder.objects.filter(pk=self.order.pk).update(notes='')
        self.assertEqual(payment_reminder.remind_all(), 0)
