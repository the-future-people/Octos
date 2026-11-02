"""
The welcome text, and the text log behind it.
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

    def make(self, **kw):
        kw.setdefault('phone', '0556244194')
        kw.setdefault('first_name', 'ama')
        with mock.patch('apps.storefront.receivers._queue'):
            return CustomerProfile.objects.create(**kw)

    def test_the_text_fits_one_sms_and_greets_by_name(self):
        c = self.make()
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
        c = self.make()
        self.assertTrue(w.welcome(c.pk))
        self.assertFalse(w.welcome(c.pk))
        self.assertEqual(post.call_count, 1)
        log = TextMessage.objects.get(kind='welcome')
        self.assertTrue(log.accepted)
        self.assertEqual(log.provider_ref, 'ABC-123')
        self.assertEqual(log.phone, '233556244194')

    @mock.patch('requests.post', side_effect=refused)
    def test_a_refusal_is_logged_and_can_be_retried(self, post):
        c = self.make()
        self.assertFalse(w.welcome(c.pk))
        log = TextMessage.objects.get(kind='welcome')
        self.assertFalse(log.accepted)
        self.assertEqual(log.provider_code, '4003')
        self.assertFalse(w.already_welcomed(c.phone))

    def test_registering_a_customer_queues_the_welcome(self):
        with mock.patch('apps.storefront.receivers._queue') as q:
            with self.captureOnCommitCallbacks(execute=True):
                c = CustomerProfile.objects.create(phone='0201112223', first_name='Kofi')
        q.assert_called_once_with(c.pk)

    def test_walk_ins_and_marked_imports_are_not_welcomed(self):
        with mock.patch('apps.storefront.receivers._queue') as q:
            with self.captureOnCommitCallbacks(execute=True):
                CustomerProfile.objects.create(phone='0201112224', is_walkin=True)
                imported = CustomerProfile(phone='0201112225', first_name='Imported')
                imported._skip_welcome = True
                imported.save()
        q.assert_not_called()

    @override_settings(WELCOME_TEXTS=False)
    def test_the_switch_turns_welcomes_off(self):
        with mock.patch('apps.storefront.receivers._queue') as q:
            with self.captureOnCommitCallbacks(execute=True):
                CustomerProfile.objects.create(phone='0201112226', first_name='Esi')
        q.assert_not_called()


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
    def test_one_welcome_per_number_across_both_doors(self, post):
        self.assertTrue(w.greet('0558631016', 'Esi'))
        with mock.patch('apps.storefront.receivers._queue'):
            c = CustomerProfile.objects.create(phone='0558631016', first_name='Esi')
        self.assertFalse(w.welcome(c.pk))
        self.assertEqual(post.call_count, 1)
