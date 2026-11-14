"""
The welcome text, and the text log behind it.

Since 14 Nov 2026 only app sign-ups are welcomed. Customers registered by
staff are thanked at the end of the day instead (tests_thanks_and_reminder).
"""

from unittest import mock

from django.test import TestCase, override_settings

from apps.customers.models import CustomerProfile
from apps.storefront.models import TextMessage
from apps.storefront.services import welcome as w


def accepted(*args, **kwargs):
    resp = mock.Mock(status_code=200)
    resp.json.return_value = {'status': 'success', 'code': '2000', 'message': 'messages sent successfully',
                              'summary': {'_id': 'ABC-123', 'credit_used': 1}}
    resp.text = ''
    return resp


def refused(*args, **kwargs):
    resp = mock.Mock(status_code=200)
    resp.json.return_value = {'status': 'error', 'code': '4003', 'message': 'invalid sender'}
    resp.text = ''
    return resp


@override_settings(MNOTIFY_API_KEY='test-key', MNOTIFY_SENDER_ID='FarhatPrint', WELCOME_TEXTS=True)
class WelcomeTests(TestCase):

    def test_the_text_fits_one_sms_and_greets_by_name(self):
        c = CustomerProfile(first_name='ama', phone='0556244194')
        text = w.welcome_text(c)
        self.assertTrue(text.startswith('Hi Ama, welcome to Farhat Printing Press!'))
        self.assertLessEqual(len(text), 160)
        self.assertTrue(text.isascii())

    def test_junk_names_drop_the_greeting(self):
        for junk in ('', 'customer', '0244', 'Walk-in'):
            c = CustomerProfile(first_name=junk, phone='0')
            self.assertTrue(w.welcome_text(c).startswith('Welcome to Farhat'), junk)

    @mock.patch('requests.post', side_effect=accepted)
    def test_sent_once_and_logged(self, post):
        self.assertTrue(w.greet('0556244194', 'ama'))
        self.assertFalse(w.greet('0556244194', 'ama'))
        self.assertEqual(post.call_count, 1)
        log = TextMessage.objects.get(kind='welcome')
        self.assertTrue(log.accepted)
        self.assertEqual(log.provider_ref, 'ABC-123')
        self.assertEqual(log.phone, '233556244194')

    @mock.patch('requests.post', side_effect=refused)
    def test_a_refusal_is_logged_and_can_be_retried(self, post):
        self.assertFalse(w.greet('0556244194', 'ama'))
        log = TextMessage.objects.get(kind='welcome')
        self.assertFalse(log.accepted)
        self.assertEqual(log.provider_code, '4003')
        self.assertFalse(w.already_welcomed('0556244194'))

    @override_settings(WELCOME_IN_TESTS=True)
    def test_registering_a_customer_sends_no_welcome(self):
        # 14 Nov 2026: it arrived at the counter, mid-job. The thank-you replaced it.
        with mock.patch('apps.storefront.services.welcome.greet') as greet:
            with self.captureOnCommitCallbacks(execute=True):
                CustomerProfile.objects.create(phone='0201112223', first_name='Kofi')
        greet.assert_not_called()


@override_settings(MNOTIFY_API_KEY='test-key', MNOTIFY_SENDER_ID='FarhatPrint', WELCOME_TEXTS=True)
class AppSignUpWelcomeTests(TestCase):
    """2 Nov 2026: app sign-ups create a lead, not a customer, and were never welcomed."""

    def sign_up(self, phone, name):
        from django.contrib.auth.hashers import make_password
        from django.core.cache import cache
        from apps.storefront.services.accounts import _code_key, normalise_phone, verify_code
        cache.set(_code_key(normalise_phone(phone)), {'hash': make_password('123456'), 'guesses': 0}, 600)
        return verify_code(phone, '123456', first_name=name)

    def test_a_new_app_account_queues_the_welcome(self):
        with mock.patch('apps.storefront.receivers._queue_greeting') as q:
            with self.captureOnCommitCallbacks(execute=True):
                self.sign_up('0558631014', 'Abena')
        q.assert_called_once()
        self.assertEqual(q.call_args[0][1], 'Abena')

    def test_signing_in_again_is_not_a_new_welcome(self):
        with mock.patch('apps.storefront.receivers._queue_greeting') as q:
            with self.captureOnCommitCallbacks(execute=True):
                self.sign_up('0558631015', 'Kwame')
            with self.captureOnCommitCallbacks(execute=True):
                self.sign_up('0558631015', '')
        self.assertEqual(q.call_count, 1)

    @mock.patch('requests.post', side_effect=accepted)
    def test_one_welcome_per_number_ever(self, post):
        self.assertTrue(w.greet('0558631016', 'Esi'))
        self.assertFalse(w.greet('0558631016', 'Esi'))
        self.assertEqual(post.call_count, 1)
