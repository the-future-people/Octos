"""
Accounts for the app: a number verified by a code, and a session.
"""

import re
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.storefront.models import AppSession, Lead
from apps.storefront.services.accounts import normalise_phone

CODE = '/api/v1/storefront/account/code/'
VERIFY = '/api/v1/storefront/account/verify/'
ME = '/api/v1/storefront/account/me/'
SIGNOUT = '/api/v1/storefront/account/signout/'


class AccountTests(TestCase):

    def setUp(self):
        cache.clear()
        self.sms = patch('apps.storefront.services.sms.send_sms').start()
        self.addCleanup(patch.stopall)

    def _code(self, phone='0244999888'):
        response = APIClient().post(CODE, {'phone': phone}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        message = self.sms.call_args[0][1]
        return re.search(r'\b(\d{6})\b', message).group(1)

    def _sign_in(self, phone='0244999888', first_name='Ama'):
        code = self._code(phone)
        response = APIClient().post(VERIFY, {'phone': phone, 'code': code, 'first_name': first_name}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def _as(self, token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'App {token}')
        return client

    # ── Numbers ──────────────────────────────────────────────────

    def test_one_number_however_it_is_written(self):
        for raw in ('0244999888', '024 499 9888', '+233 24 499 9888', '233244999888', '244999888'):
            self.assertEqual(normalise_phone(raw), '+233244999888', raw)
        self.assertIsNone(normalise_phone('12345'))

    def test_a_website_customer_signs_in_to_the_same_account(self):
        Lead.objects.create(phone='024 499 9888', first_name='Ama')
        self._sign_in('+233244999888', first_name='')
        self.assertEqual(Lead.objects.count(), 1)

    # ── Signing up and in ────────────────────────────────────────

    def test_a_new_number_signs_up_with_a_first_name(self):
        data = self._sign_in()
        self.assertTrue(data['token'])
        self.assertEqual(data['account']['first_name'], 'Ama')
        self.assertEqual(Lead.objects.get().phone, '+233244999888')

    def test_a_new_number_needs_a_first_name(self):
        code = self._code()
        response = APIClient().post(VERIFY, {'phone': '0244999888', 'code': code}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_the_token_is_never_stored_as_given(self):
        token = self._sign_in()['token']
        self.assertFalse(AppSession.objects.filter(token_hash=token).exists())

    # ── The code's limits ────────────────────────────────────────

    def test_five_wrong_guesses_kill_the_code(self):
        # Checked on the service itself: through the API, the per-device
        # limit (next test) steps in first and hides this rule.
        from apps.storefront.services.accounts import AccountRefused, verify_code
        code = self._code()
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(5):
            with self.assertRaises(AccountRefused):
                verify_code('0244999888', wrong, first_name='Ama')
        # Even the right code is refused now: the code is dead.
        with self.assertRaises(AccountRefused):
            verify_code('0244999888', code, first_name='Ama')

    def test_one_device_cannot_hammer_the_codes(self):
        self._code()
        statuses = [
            APIClient().post(VERIFY, {'phone': '0244999888', 'code': '123456', 'first_name': 'Ama'}, format='json').status_code
            for _ in range(8)
        ]
        self.assertIn(429, statuses)

    def test_a_number_gets_three_codes_in_fifteen_minutes(self):
        for _ in range(3):
            self._code()
        response = APIClient().post(CODE, {'phone': '0244999888'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_a_code_works_once(self):
        code = self._code()
        first = APIClient().post(VERIFY, {'phone': '0244999888', 'code': code, 'first_name': 'Ama'}, format='json')
        again = APIClient().post(VERIFY, {'phone': '0244999888', 'code': code, 'first_name': 'Ama'}, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.status_code, 400)

    # ── Sessions ─────────────────────────────────────────────────

    def test_the_token_says_who_is_signed_in(self):
        token = self._sign_in()['token']
        response = self._as(token).get(ME)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['first_name'], 'Ama')
        self.assertEqual(response.json()['phone'], '024 ••• 9888')

    def test_without_a_token_nobody_is_signed_in(self):
        self.assertEqual(APIClient().get(ME).status_code, 401)
        self.assertEqual(self._as('made-up').get(ME).status_code, 401)

    def test_signing_out_ends_the_session(self):
        token = self._sign_in()['token']
        self.assertEqual(self._as(token).post(SIGNOUT).status_code, 200)
        self.assertEqual(self._as(token).get(ME).status_code, 401)

    def test_a_customer_can_change_their_first_name(self):
        token = self._sign_in()['token']
        response = self._as(token).patch(ME, {'first_name': 'Jimmy'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['first_name'], 'Jimmy')
        self.assertTrue(response.json()['member_since'])
        self.assertEqual(self._as(token).patch(ME, {'first_name': '  '}, format='json').status_code, 400)


class MyOrdersTests(TestCase):
    """The signed-in customer's orders: every paid one on their number."""

    def setUp(self):
        cache.clear()
        self.sms = patch('apps.storefront.services.sms.send_sms').start()
        self.addCleanup(patch.stopall)

    def _token(self, phone='0244999888'):
        APIClient().post(CODE, {'phone': phone}, format='json')
        code = re.search(r'\b(\d{6})\b', self.sms.call_args[0][1]).group(1)
        return APIClient().post(VERIFY, {'phone': phone, 'code': code, 'first_name': 'Ama'},
                                format='json').json()['token']

    def _order(self, lead, paid=True):
        from decimal import Decimal
        from django.utils import timezone
        from apps.storefront.models import OnlineOrder
        order = OnlineOrder.objects.create(lead=lead, total=Decimal('58.50'),
                                           full_total=Decimal('58.50'))
        if paid:
            order.paid_at = timezone.now()
            order.save(update_fields=['paid_at'])
        return order

    def _orders(self, token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'App {token}')
        return client.get('/api/v1/storefront/account/orders/')

    def test_paid_orders_on_the_number_are_listed_with_their_link(self):
        token = self._token()
        lead = Lead.objects.get()
        order = self._order(lead)

        data = self._orders(token).json()

        self.assertEqual([o['order_number'] for o in data['active']], [order.order_number])
        self.assertEqual(data['active'][0]['token'], order.access_token)
        self.assertEqual(data['collected'], [])

    def test_a_cart_never_paid_for_is_not_an_order(self):
        token = self._token()
        self._order(Lead.objects.get(), paid=False)
        self.assertEqual(self._orders(token).json()['active'], [])

    def test_the_number_written_another_way_is_the_same_customer(self):
        website = Lead.objects.create(phone='024 499 9888', first_name='Ama')
        order = self._order(website)
        token = self._token('0244999888')

        numbers = [o['order_number'] for o in self._orders(token).json()['active']]
        self.assertIn(order.order_number, numbers)

    def test_someone_elses_orders_never_show(self):
        other = Lead.objects.create(phone='0201112222', first_name='Kofi')
        self._order(other)
        token = self._token()
        self.assertEqual(self._orders(token).json()['active'], [])

    def test_orders_need_a_signed_in_app(self):
        self.assertEqual(APIClient().get('/api/v1/storefront/account/orders/').status_code, 401)


    def test_each_order_says_its_size_or_quantity(self):
        from apps.storefront.services.accounts import _detail
        self.assertEqual(_detail({'quantity': 1, 'specifications': {'width_in': 36, 'height_in': 72}}), '3ft × 6ft')
        self.assertEqual(_detail({'quantity': 3, 'specifications': {'width_in': 12, 'height_in': 18}}), '1ft × 18in · 3 pieces')
        self.assertEqual(_detail({'quantity': 100, 'service_name': 'A4 Colour Printing', 'specifications': {}}), '100 copies')
        self.assertEqual(_detail({'quantity': 2, 'base_name': 'Business Cards', 'specifications': {}}), '2 boxes')

    def test_the_list_has_a_place_for_cancelled_orders(self):
        token = self._token()
        self.assertIn('cancelled', self._orders(token).json())
