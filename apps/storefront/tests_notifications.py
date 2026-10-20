"""
Telling customers: push to the app first, SMS when no phone is reached,
and an inbox of everything told.
"""

import re
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.storefront.models import AppNotification, DeviceToken, Lead, OnlineOrder
from apps.storefront.services.notify import tell


class NotifyTests(TestCase):

    def setUp(self):
        cache.clear()
        self.sms = patch('apps.storefront.services.sms.send_sms').start()
        self.addCleanup(patch.stopall)

    def _signed_in(self, phone='0244999888'):
        client = APIClient()
        client.post('/api/v1/storefront/account/code/', {'phone': phone}, format='json')
        code = re.search(r'\b(\d{6})\b', self.sms.call_args[0][1]).group(1)
        token = client.post('/api/v1/storefront/account/verify/',
                            {'phone': phone, 'code': code, 'first_name': 'Ama'},
                            format='json').json()['token']
        client.credentials(HTTP_AUTHORIZATION=f'App {token}')
        self.sms.reset_mock()
        return client

    def _order(self):
        order = OnlineOrder.objects.create(
            lead=Lead.objects.get(), total=Decimal('58.50'), full_total=Decimal('58.50'),
            paid_at=timezone.now(),
        )
        return order

    def _device(self, client, token='phone-1'):
        response = client.post('/api/v1/storefront/account/device/',
                               {'token': token, 'platform': 'android'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)

    # ── Push first, SMS when nobody is reached ───────────────────

    def test_a_phone_with_the_app_is_pushed_and_not_texted(self):
        client = self._signed_in()
        self._device(client)
        with patch('apps.storefront.services.push.send', return_value=True) as push:
            note = tell(self._order(), 'ready', 'Ready to collect', 'Your order is ready.', 'SMS text')
        push.assert_called_once()
        self.sms.assert_not_called()
        self.assertTrue(note.pushed)
        self.assertFalse(note.texted)

    def test_no_app_means_an_sms_as_before(self):
        self._signed_in()
        note = tell(self._order(), 'ready', 'Ready to collect', 'Your order is ready.', 'SMS text')
        self.sms.assert_called_once()
        self.assertTrue(note.texted)

    def test_a_push_that_fails_falls_back_to_sms(self):
        client = self._signed_in()
        self._device(client)
        with patch('apps.storefront.services.push.send', return_value=False):
            note = tell(self._order(), 'ready', 'Ready to collect', 'Ready.', 'SMS text')
        self.sms.assert_called_once()
        self.assertFalse(note.pushed)

    def test_a_phone_that_has_gone_is_forgotten(self):
        from apps.storefront.services.push import TokenGone
        client = self._signed_in()
        self._device(client)
        with patch('apps.storefront.services.push.send', side_effect=TokenGone()):
            tell(self._order(), 'ready', 'Ready to collect', 'Ready.', 'SMS text')
        self.assertFalse(DeviceToken.objects.exists())
        self.sms.assert_called_once()

    def test_signing_out_stops_that_phone_being_pushed(self):
        client = self._signed_in()
        self._device(client)
        client.post('/api/v1/storefront/account/signout/')
        with patch('apps.storefront.services.push.send', return_value=True) as push:
            tell(self._order(), 'ready', 'Ready to collect', 'Ready.', 'SMS text')
        push.assert_not_called()
        self.sms.assert_called_once()

    # ── The inbox ────────────────────────────────────────────────

    def test_the_inbox_lists_what_was_told_and_counts_unread(self):
        client = self._signed_in()
        order = self._order()
        tell(order, 'paid', 'Payment received', 'We’re on it.', 'SMS')
        tell(order, 'ready', 'Ready to collect', 'Your order is ready.', 'SMS')

        data = client.get('/api/v1/storefront/account/notifications/').json()
        self.assertEqual(data['unread'], 2)
        self.assertEqual([n['kind'] for n in data['items']], ['ready', 'paid'])
        self.assertEqual(data['items'][0]['order_number'], order.order_number)

        client.post('/api/v1/storefront/account/notifications/read/')
        self.assertEqual(client.get('/api/v1/storefront/account/notifications/').json()['unread'], 0)

    def test_the_inbox_needs_a_signed_in_app(self):
        self.assertEqual(APIClient().get('/api/v1/storefront/account/notifications/').status_code, 401)

    def test_a_nudge_is_silent(self):
        """No title, no body: only data, so nothing shows on the phone."""
        from apps.storefront.services import push
        creds = type('Creds', (), {'project_id': 'p', 'token': 't'})()
        with patch.object(push, '_creds', return_value=creds), \
             patch('apps.storefront.services.push.requests.post') as post:
            post.return_value.status_code = 200
            push.nudge('phone-9', {'kind': 'nudge', 'order': 'ORD-1'})
        message = post.call_args.kwargs['json']['message']
        self.assertNotIn('notification', message)
        self.assertEqual(message['data'], {'kind': 'nudge', 'order': 'ORD-1'})

    def test_a_job_with_no_online_order_nudges_nobody(self):
        """Counter jobs have no app to nudge."""
        from apps.storefront.tasks import nudge_app
        with patch('apps.storefront.services.push.configured', return_value=True), \
             patch('apps.storefront.services.push.nudge') as nudge:
            nudge_app(999999)
        nudge.assert_not_called()