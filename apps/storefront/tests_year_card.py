"""
The year-end card: a customer's year, only what is true, behind a private code.
"""

from datetime import datetime
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.customers.models import CustomerProfile
from apps.jobs.models import Job, JobLineItem, Service
from apps.organization.models import Branch
from apps.storefront.models import TextMessage, YearCard
from apps.storefront.services import year_card as yc


def accepted(*a, **k):
    r = mock.Mock(status_code=200, text='')
    r.json.return_value = {'status': 'success', 'code': '2000', 'summary': {'_id': 'X', 'credit_used': 1}}
    return r


@override_settings(MNOTIFY_API_KEY='k', MNOTIFY_SENDER_ID='FarhatPrint', STOREFRONT_HOST='print-octos.vercel.app')
class YearCardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name='Card Westland', code='CDWL', address='x')
        cls.banner = Service.objects.create(name='Flexy Banner 6ft', code='CDBAN', category='PRODUCTION',
                                            unit='PER_SQFT', requires_design=False, requires_file_upload=True,
                                            is_active=True)
        cls.cards = Service.objects.create(name='Business Cards', code='CDBC', category='PRODUCTION',
                                           unit='PER_BOX', requires_design=False, requires_file_upload=True,
                                           is_active=True)

    def customer(self, phone, name='Ama'):
        with mock.patch('apps.storefront.receivers._queue'):
            return CustomerProfile.objects.create(phone=phone, first_name=name)

    def job(self, customer, when, service, status='PAID'):
        j = Job.objects.create(branch=self.branch, job_type='PRODUCTION', title='t', customer=customer, status=status)
        JobLineItem.objects.create(job=j, service=service, quantity=1, pages=1)
        Job.objects.filter(pk=j.pk).update(created_at=timezone.make_aware(when))
        return j

    def test_a_customers_year_from_their_own_orders(self):
        c = self.customer('0559000001')
        self.job(c, datetime(2026, 3, 4), self.banner)
        self.job(c, datetime(2026, 10, 2), self.banner)
        self.job(c, datetime(2026, 10, 20), self.cards)
        self.job(c, datetime(2026, 11, 1), self.banner, status='CANCELLED')
        self.job(c, datetime(2025, 6, 1), self.cards)
        s = yc.year_of(c, 2026)
        self.assertEqual(s['orders'], 3)
        self.assertEqual(s['favourite'], 'Flexy Banner')
        self.assertEqual(s['first_month'], 'March')
        self.assertEqual((s['biggest_month'], s['biggest_count']), ('October', 2))

    def test_no_orders_means_the_thank_you_card(self):
        c = self.customer('0559000002', 'Kofi')
        card = yc.card_for(c, 2026)
        self.assertEqual(card.kind, YearCard.FAMILY)
        self.assertEqual(card.stats, {})

    def test_one_month_is_not_a_biggest_month(self):
        c = self.customer('0559000003')
        self.job(c, datetime(2026, 5, 5), self.banner)
        self.assertEqual(yc.year_of(c, 2026)['biggest_month'], '')

    def test_the_text_is_one_ascii_sms_with_the_link(self):
        c = self.customer('0559000004', 'Christabelle')
        card = yc.card_for(c, 2026)
        text = yc.card_text(card)
        self.assertLessEqual(len(text), 160)
        self.assertTrue(text.isascii())
        self.assertIn(f'/y/{card.code}', text)
        self.assertIn('Afehyia pa', text)

    def test_the_page_opens_by_code_and_is_marked_opened(self):
        c = self.customer('0559000005')
        self.job(c, datetime(2026, 2, 2), self.banner)
        card = yc.card_for(c, 2026)
        resp = APIClient().get(f'/api/v1/storefront/y/{card.code.lower()}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['first_name'], 'Ama')
        self.assertEqual(resp.data['stats']['orders'], 1)
        card.refresh_from_db()
        self.assertIsNotNone(card.opened_at)
        self.assertEqual(APIClient().get('/api/v1/storefront/y/NOPE1234/').status_code, 404)

    @mock.patch('requests.post', side_effect=accepted)
    def test_send_is_once_per_number_and_a_dry_run_sends_nothing(self, post):
        self.customer('0559000006')
        self.customer('0559000007', 'Kwame')
        call_command('year_end_cards', '--year', '2026')
        self.assertEqual(post.call_count, 0)
        call_command('year_end_cards', '--year', '2026', '--send', '--pause', '0')
        first = post.call_count
        self.assertGreaterEqual(first, 2)
        call_command('year_end_cards', '--year', '2026', '--send', '--pause', '0')
        self.assertEqual(post.call_count, first)
        self.assertEqual(TextMessage.objects.filter(kind='yearcard-2026', accepted=True).count(), first)
