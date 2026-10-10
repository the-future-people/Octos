from decimal import Decimal
import json
from django.test import TestCase
from django.utils import timezone

from apps.storefront.models import Lead, OnlineOrder
from apps.storefront.models import Lead, OnlineOrder, PaystackEvent

class LeadTests(TestCase):
    """
    A first visit creates a lead, not a customer. Most first visits never
    come back, and writing every one into CustomerProfile would fill the
    customer table with people the shop has met once.
    """

    def setUp(self):
        # Throttle counts live in the cache and do not roll back with
        # the test transaction, so a class of fifteen requests trips the
        # limiter and every test after it reads as broken.
        from django.core.cache import cache
        cache.clear()
    
    def test_a_new_lead_is_not_returning_and_has_no_code(self):
        lead = Lead.objects.create(phone='0244000001', first_name='Ama')
        self.assertFalse(lead.is_returning)
        self.assertFalse(lead.has_code)

    def test_a_code_is_hashed_never_stored_as_typed(self):
        """
        The code opens a customer's order history, so a readable column
        would be a list of working keys. Losing it means being sent a
        new one, not being told the old one.
        """
        lead = Lead.objects.create(phone='0244000002', first_name='Kofi')
        lead.set_code('AMA-4K2')
        lead.save()
        lead.refresh_from_db()

        self.assertNotEqual(lead.code, 'AMA-4K2')
        self.assertNotIn('AMA-4K2', lead.code)
        self.assertTrue(lead.check_code('AMA-4K2'))
        self.assertFalse(lead.check_code('AMA-4K3'))

    def test_a_phone_number_belongs_to_one_lead(self):
        from django.db import IntegrityError
        Lead.objects.create(phone='0244000003', first_name='Yaa')
        with self.assertRaises(IntegrityError):
            Lead.objects.create(phone='0244000003', first_name='Someone else')


class OnlineOrderTests(TestCase):
    """
    An order exists from the moment someone starts building it, before
    any branch knows about it and before anyone has paid. Most are
    abandoned, which costs nothing.
    """

    def _order(self, **overrides):
        defaults = dict(total=Decimal('568.75'))
        defaults.update(overrides)
        return OnlineOrder.objects.create(**defaults)

    def test_an_order_numbers_itself(self):
        order = self._order()
        year = timezone.localdate().year
        self.assertTrue(order.order_number.startswith(f'ORD-{year}-'))

    def test_every_order_gets_its_own_number(self):
        """
        From a sequence, not from the highest so far. Two strangers can
        click in the same millisecond.
        """
        numbers = {self._order().order_number for _ in range(5)}
        self.assertEqual(len(numbers), 5)

    def test_an_order_starts_as_a_draft_owned_by_nobody(self):
        order = self._order()
        self.assertEqual(order.status, OnlineOrder.Status.DRAFT)
        self.assertIsNone(order.branch_id)
        self.assertIsNone(order.lead_id)
        self.assertIsNone(order.job_id)
        self.assertFalse(order.is_paid)
        self.assertTrue(order.is_open)

    def test_an_order_is_not_paid_until_the_webhook_says_so(self):
        """
        paid_at is set by the provider's callback, never by the customer
        returning to the page. Someone who closes the tab after paying
        has still paid.
        """
        order = self._order(
            status=OnlineOrder.Status.AWAITING_PAYMENT,
            payment_reference='ORD-TEST-REF-001',
        )
        self.assertFalse(order.is_paid)

        order.paid_at = timezone.now()
        order.status = OnlineOrder.Status.PAID
        order.save()

        self.assertTrue(order.is_paid)
        self.assertFalse(order.is_open)

    def test_line_items_carry_the_specification(self):
        """
        A banner's size has to survive into the job, or the floor gets a
        banner with no dimensions on it.
        """
        order = self._order(line_items=[{
            'service_name': 'Flexy Banner',
            'quantity': 1,
            'unit_price': '568.75',
            'total': '568.75',
            'specifications': {'width_in': 168, 'height_in': 150},
        }])
        order.refresh_from_db()
        self.assertEqual(
            order.line_items[0]['specifications']['width_in'], 168,
        )

class StorefrontAPITests(TestCase):
    """
    The first endpoints in Octos that anyone can call. Everything else
    requires a staff JWT; a stranger pricing a banner has no account and
    should not need one to find out what it costs.

    What stands in for an account is a token on the order, returned once
    and required afterwards. The order number is sequential and
    guessable, so it can never be what proves the order is yours.
    """

    def setUp(self):
        # Throttle counts live in the cache and do not roll back with
        # the test transaction, so a class of fifteen requests trips the
        # limiter and every test after it reads as broken.
        from django.core.cache import cache
        cache.clear()

    @classmethod
    def setUpTestData(cls):
        import datetime
        from apps.organization.models import Branch
        from apps.jobs.models import Service, PricingRule

        cls.branch = Branch.objects.create(
            name='Storefront Branch', code='SFB',
            is_headquarters=False, is_regional_hq=False,
            address='1 Storefront Road',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30),
            closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )
        cls.flexy = Service.objects.create(
            name='Storefront Flexy', code='SFFLEXY',
            category='PRODUCTION', unit='PER_SQFT',
            requires_design=False, requires_file_upload=True,
            is_active=True,
            spec_template=[
                {'key': 'width_in', 'label': 'Width', 'type': 'number',
                 'required': True, 'default': 72, 'min': 6, 'unit': 'in'},
                {'key': 'height_in', 'label': 'Height', 'type': 'number',
                 'required': True, 'default': 36, 'min': 6, 'unit': 'in'},
            ],
        )
        # Company-wide: prices are set once and ripple to every branch.
        PricingRule.objects.create(
            service=cls.flexy, branch=None,
            base_price=Decimal('3.25'),
            color_multiplier=Decimal('1.00'),
            minimum_price=Decimal('10.00'),
            is_active=True,
        )

    def _client(self):
        from rest_framework.test import APIClient
        return APIClient()

    # ── Catalogue ──────────────────────────────────────────────────

    def test_the_catalogue_is_readable_without_an_account(self):
        response = self._client().get('/api/v1/storefront/catalogue/')
        self.assertEqual(response.status_code, 200, response.content)
        codes = {s['code'] for s in response.data}
        self.assertIn('SFFLEXY', codes)

    def test_the_catalogue_carries_what_the_form_needs(self):
        response = self._client().get('/api/v1/storefront/catalogue/')
        service = next(s for s in response.data if s['code'] == 'SFFLEXY')
        self.assertTrue(service['spec_template'])
        self.assertEqual(service['unit'], 'PER_SQFT')

    # ── Creating an order ──────────────────────────────────────────

    def test_starting_an_order_returns_a_number_and_a_token(self):
        response = self._client().post('/api/v1/storefront/orders/', {}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.data['order_number'].startswith('ORD-'))
        self.assertTrue(response.data['access_token'])
        self.assertEqual(response.data['status'], 'DRAFT')

    def test_an_order_belongs_to_nobody_when_it_starts(self):
        response = self._client().post('/api/v1/storefront/orders/', {}, format='json')
        self.assertIsNone(response.data['branch'])
        self.assertEqual(response.data['total'], '0.00')

    # ── Reading one back ───────────────────────────────────────────

    def test_the_token_is_what_opens_an_order(self):
        created = self._client().post('/api/v1/storefront/orders/', {}, format='json').data
        response = self._client().get(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {'token': created['access_token']},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['order_number'], created['order_number'])

    def test_the_order_number_alone_opens_nothing(self):
        """
        ORD-2026-00001 is a guess away from ORD-2026-00002. Without the
        token, knowing the number must be worth nothing.
        """
        created = self._client().post('/api/v1/storefront/orders/', {}, format='json').data
        response = self._client().get(
            f"/api/v1/storefront/orders/{created['order_number']}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_somebody_elses_token_opens_nothing(self):
        mine = self._client().post('/api/v1/storefront/orders/', {}, format='json').data
        theirs = self._client().post('/api/v1/storefront/orders/', {}, format='json').data
        response = self._client().get(
            f"/api/v1/storefront/orders/{mine['order_number']}/",
            {'token': theirs['access_token']},
        )
        self.assertEqual(response.status_code, 404)

    # ── Adding to it ───────────────────────────────────────────────

    def test_a_line_is_priced_by_the_server_not_by_what_was_sent(self):
        """
        A price arriving from a browser is a suggestion from a stranger.
        The server quotes it again from the specification.
        """
        created = self._client().post('/api/v1/storefront/orders/', {}, format='json').data
        response = self._client().patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {
                'token': created['access_token'],
                'line_items': [{
                    'service': self.flexy.id,
                    'quantity': 1,
                    'specifications': {'width_in': 168, 'height_in': 150},
                    'total': '1.00',
                }],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['total'], '568.75')
        self.assertEqual(response.data['line_items'][0]['total'], '568.75')

    def test_a_line_without_its_dimensions_is_refused(self):
        created = self._client().post('/api/v1/storefront/orders/', {}, format='json').data
        response = self._client().patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {
                'token': created['access_token'],
                'line_items': [{'service': self.flexy.id, 'quantity': 1}],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_a_paid_order_cannot_be_edited(self):
        created = self._client().post('/api/v1/storefront/orders/', {}, format='json').data
        order = OnlineOrder.objects.get(order_number=created['order_number'])
        order.status = OnlineOrder.Status.PAID
        order.paid_at = timezone.now()
        order.save()

        response = self._client().patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {
                'token': created['access_token'],
                'line_items': [{
                    'service': self.flexy.id, 'quantity': 1,
                    'specifications': {'width_in': 12, 'height_in': 12},
                }],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 409)

class IdentityTests(TestCase):
    """
    Identity is asked for late and lightly. A stranger pricing a banner
    should know what it costs before being asked who they are, and a
    customer coming back should not be challenged at the door.

    A code is offered, never demanded. Someone who skips it loses
    nothing they had.
    """

    def setUp(self):
        # Throttle counts live in the cache and do not roll back with
        # the test transaction, so a class of fifteen requests trips the
        # limiter and every test after it reads as broken.
        from django.core.cache import cache
        cache.clear()

    def _client(self):
        from rest_framework.test import APIClient
        return APIClient()

    def _order(self, total='568.75'):
        client = self._client()
        created = client.post('/api/v1/storefront/orders/', {}, format='json').data
        order = OnlineOrder.objects.get(order_number=created['order_number'])
        order.full_total = Decimal(total)
        order.total = Decimal(total)
        order.save()
        return created

    def _identify(self, created, **extra):
        payload = {'token': created['access_token'],
                   'phone': '0244111222', 'first_name': 'Ama'}
        payload.update(extra)
        return self._client().post(
            f"/api/v1/storefront/orders/{created['order_number']}/identify/",
            payload, format='json',
        )

    # ── A first-time customer ──────────────────────────────────────

    def test_a_new_number_becomes_a_lead_and_is_attached(self):
        created = self._order()
        response = self._identify(created)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.data['returning'])
        self.assertFalse(response.data['code_required'])

        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertEqual(order.lead.phone, '0244111222')
        self.assertEqual(order.lead.first_name, 'Ama')

    def test_identifying_needs_the_orders_token(self):
        created = self._order()
        response = self._client().post(
            f"/api/v1/storefront/orders/{created['order_number']}/identify/",
            {'phone': '0244111222', 'first_name': 'Ama'}, format='json',
        )
        self.assertEqual(response.status_code, 404)

    # ── Coming back ────────────────────────────────────────────────

    def test_a_returning_number_without_a_code_attaches_freely(self):
        """
        Being challenged on the visit you came back is the wrong moment.
        Nothing is protected yet, which is the customer's own choice.
        """
        Lead.objects.create(phone='0244111222', first_name='Ama', order_count=1)
        created = self._order()
        response = self._identify(created)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data['returning'])
        self.assertFalse(response.data['code_required'])

    def test_a_returning_number_with_a_code_is_asked_for_it(self):
        lead = Lead.objects.create(phone='0244111222', first_name='Ama', order_count=2)
        lead.set_code('AMA-4K2')
        lead.save()

        created = self._order()
        response = self._identify(created)

        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.data['code_required'])

        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertIsNone(order.lead_id)

    def test_the_right_code_attaches_the_order(self):
        lead = Lead.objects.create(phone='0244111222', first_name='Ama', order_count=2)
        lead.set_code('AMA-4K2')
        lead.save()

        created = self._order()
        response = self._identify(created, code='AMA-4K2')

        self.assertEqual(response.status_code, 200, response.content)
        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertEqual(order.lead_id, lead.id)

    def test_a_wrong_code_attaches_nothing(self):
        lead = Lead.objects.create(phone='0244111222', first_name='Ama', order_count=2)
        lead.set_code('AMA-4K2')
        lead.save()

        created = self._order()
        response = self._identify(created, code='AMA-9Z9')

        self.assertEqual(response.status_code, 401)
        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertIsNone(order.lead_id)


class CodeDiscountTests(TestCase):
    """
    5% for setting a code, once per person, on orders over GHS 100. A
    cedi off a photocopy delights nobody; thirty off a banner is a
    reason to come back.
    """


    def setUp(self):
        # Throttle counts live in the cache and do not roll back with
        # the test transaction, so a class of fifteen requests trips the
        # limiter and every test after it reads as broken.
        from django.core.cache import cache
        cache.clear()

        
    def _client(self):
        from rest_framework.test import APIClient
        return APIClient()

    def _identified_order(self, total='617.50', phone='0244333444'):
        client = self._client()
        created = client.post('/api/v1/storefront/orders/', {}, format='json').data
        order = OnlineOrder.objects.get(order_number=created['order_number'])
        order.full_total = Decimal(total)
        order.total = Decimal(total)
        order.save()
        client.post(
            f"/api/v1/storefront/orders/{created['order_number']}/identify/",
            {'token': created['access_token'], 'phone': phone, 'first_name': 'Kofi'},
            format='json',
        )
        return created

    def _set_code(self, created):
        return self._client().post(
            f"/api/v1/storefront/orders/{created['order_number']}/code/",
            {'token': created['access_token']}, format='json',
        )
    def test_setting_a_code_takes_five_percent_off(self):
        created = self._identified_order('617.50', phone='0244777001')
        response = self._set_code(created)

        self.assertEqual(response.status_code, 200, response.content)
        order = OnlineOrder.objects.get(order_number=created['order_number'])
        # 5% of 617.50 is 30.875, to the nearest cedi.
        self.assertEqual(order.discount_amount, Decimal('31.00'))
        self.assertEqual(order.full_total, Decimal('617.50'))
        self.assertEqual(order.total, Decimal('586.50'))

    def test_the_code_comes_back_once_and_is_stored_hashed(self):
        created = self._identified_order(phone='0244777002')
        response = self._set_code(created)

        code = response.data['code']
        self.assertTrue(code)

        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertNotEqual(order.lead.code, code)
        self.assertTrue(order.lead.check_code(code))

    def test_a_small_order_gets_a_code_but_no_discount(self):
        created = self._identified_order('80.00', phone='0244777003')
        response = self._set_code(created)

        self.assertEqual(response.status_code, 200, response.content)
        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertEqual(order.discount_amount, Decimal('0.00'))
        self.assertEqual(order.total, Decimal('80.00'))
        self.assertTrue(order.lead.has_code)

    def test_the_discount_is_paid_once_per_person(self):
        """
        Held against the person, not the code, so clearing a code and
        setting another earns nothing new.
        """
        first = self._identified_order('617.50', phone='0244555666')
        self._set_code(first)

        second = self._identified_order('400.00', phone='0244555666')
        self._set_code(second)

        order = OnlineOrder.objects.get(order_number=second['order_number'])
        self.assertEqual(order.discount_amount, Decimal('0.00'))
        self.assertEqual(order.total, Decimal('400.00'))

    def test_a_code_cannot_be_set_on_an_order_with_nobody_on_it(self):
        client = self._client()
        created = client.post('/api/v1/storefront/orders/', {}, format='json').data
        response = self._set_code(created)
        self.assertEqual(response.status_code, 400)

class PaymentFeeTests(TestCase):
    """
    Paystack Ghana takes 1.95% of every local transaction — cards,
    mobile money and bank alike — with no flat fee and no cap.

    Both figures are kept. The day sheet shows what the work earned, so
    a banner sold online is comparable with the same banner sold at the
    counter, and it shows what actually arrived, so the day reconciles
    against the bank. Neither number stands in for the other.
    """

    def _fee(self, amount):
        from apps.storefront.services.fees import split_payment
        return split_payment(Decimal(amount))

    def test_the_fee_is_taken_from_what_the_customer_paid(self):
        gross, fee, net = self._fee('568.75')
        self.assertEqual(gross, Decimal('568.75'))
        self.assertEqual(fee, Decimal('11.09'))
        self.assertEqual(net, Decimal('557.66'))

    def test_the_three_figures_always_reconcile(self):
        """Whatever the rounding does, the fee and the net must add back
        to what the customer was charged."""
        for amount in ('10.00', '99.99', '100.00', '617.50', '1234.56'):
            gross, fee, net = self._fee(amount)
            self.assertEqual(fee + net, gross, f'failed on {amount}')

    def test_a_small_payment_still_carries_a_fee(self):
        """No cap and no minimum in Ghana — 1.95% of everything."""
        gross, fee, net = self._fee('10.00')
        self.assertEqual(fee, Decimal('0.20'))
        self.assertEqual(net, Decimal('9.80'))

class PaystackWebhookTests(TestCase):
    """
    What marks an order paid. Not the customer returning to the page:
    someone who closes the tab after paying has still paid, and someone
    who reaches the success page without paying has not.

    The webhook does the least it can — records the payment, marks the
    order, returns. Paystack retries anything slow or failed, and a
    webhook that tries to convert a job, pick a branch and write a
    receipt is one that fails halfway through.
    """

    URL = '/api/v1/storefront/webhook/paystack/'

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _order(self, total='568.75', reference='ORD-TEST-REF-1'):
        order = OnlineOrder.objects.create(
            full_total=Decimal(total),
            total=Decimal(total),
            status=OnlineOrder.Status.AWAITING_PAYMENT,
            payment_reference=reference,
        )
        return order

    def _post(self, body, signature=None):
        import json
        from rest_framework.test import APIClient

        raw = json.dumps(body)
        if signature is None:
            signature = self._sign(raw)
        return APIClient().post(
            self.URL, raw, content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

    @staticmethod
    def _sign(raw):
        import hashlib
        import hmac
        from django.conf import settings
        secret = getattr(settings, 'PAYSTACK_SECRET_KEY', 'test-secret')
        return hmac.new(
            secret.encode(), raw.encode(), hashlib.sha512,
        ).hexdigest()

    def _event(self, reference='ORD-TEST-REF-1', amount=56875):
        """Paystack sends amounts in the smallest unit — pesewas."""
        return {
            'event': 'charge.success',
            'data': {
                'reference': reference,
                'amount': amount,
                'status': 'success',
                'channel': 'mobile_money',
                'id': 998877,
            },
        }

    # ── The signature ──────────────────────────────────────────────

    def test_an_unsigned_event_is_refused(self):
        """
        Without this, anyone who finds the URL can mark orders paid.
        """
        order = self._order()
        response = self._post(self._event(), signature='not-a-signature')

        self.assertEqual(response.status_code, 401)
        order.refresh_from_db()
        self.assertFalse(order.is_paid)

    def test_a_signed_event_marks_the_order_paid(self):
        order = self._order()
        response = self._post(self._event())

        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        self.assertTrue(order.is_paid)
        self.assertEqual(order.status, OnlineOrder.Status.PAID)

    # ── The money ──────────────────────────────────────────────────

    def test_the_fee_and_the_net_are_recorded(self):
        order = self._order('568.75')
        self._post(self._event())

        order.refresh_from_db()
        self.assertEqual(order.total, Decimal('568.75'))
        self.assertEqual(order.payment_fee, Decimal('11.09'))
        self.assertEqual(order.net_received, Decimal('557.66'))

    def test_an_amount_that_does_not_match_the_order_is_refused(self):
        """
        The event says what was paid. If it is not what the order says,
        something is wrong and nobody should be printing a banner.
        """
        order = self._order('568.75')
        response = self._post(self._event(amount=1000))

        self.assertEqual(response.status_code, 400)
        order.refresh_from_db()
        self.assertFalse(order.is_paid)

    # ── Arriving twice ─────────────────────────────────────────────

    def test_the_same_event_twice_pays_the_order_once(self):
        """
        Paystack retries. A duplicate must not count the money twice.
        """
        order = self._order()
        first = self._post(self._event())
        second = self._post(self._event())

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

        order.refresh_from_db()
        self.assertEqual(order.payment_fee, Decimal('11.09'))
        self.assertEqual(
            PaystackEvent.objects.filter(reference='ORD-TEST-REF-1').count(), 1,
        )

    # ── Everything else ────────────────────────────────────────────

    def test_an_unknown_reference_is_acknowledged_not_retried(self):
        """
        A 200 with nothing done. Refusing would make Paystack retry an
        event that will never match anything.
        """
        response = self._post(self._event(reference='ORD-NOBODY'))
        self.assertEqual(response.status_code, 200)

    def test_an_event_we_do_not_act_on_is_acknowledged(self):
        order = self._order()
        body = self._event()
        body['event'] = 'charge.failed'
        response = self._post(body)

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertFalse(order.is_paid)

class PaymentInitTests(TestCase):
    """
    Handing an order to Paystack.

    The reference sent is ours, so the webhook can name the order the
    money belongs to. Paystack returns a URL and the customer is sent
    there — nothing about the payment happens on our pages.
    """

    URL_FOR = '/api/v1/storefront/orders/{}/pay/'

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _client(self):
        from rest_framework.test import APIClient
        return APIClient()

    def _order(self, total='568.75', with_lead=True):
        order = OnlineOrder.objects.create(
            full_total=Decimal(total), total=Decimal(total),
        )
        if with_lead:
            order.lead = Lead.objects.create(
                phone='0244999888', first_name='Ama',
            )
            # Payment needs somewhere to make the job. These tests are
            # about what happens at Paystack, so the branch is set
            # directly rather than chosen through capability.
            order.branch = self.branch
            order.save()
        return order
    
    def _pay(self, order, **extra):
        payload = {'token': order.access_token}
        payload.update(extra)
        return self._client().post(
            self.URL_FOR.format(order.order_number), payload, format='json',
        )

    def test_starting_a_payment_returns_somewhere_to_send_the_customer(self):
        from unittest.mock import patch

        order = self._order()
        with patch('apps.storefront.services.paystack.initialise') as init:
            init.return_value = {
                'success': True,
                'authorization_url': 'https://checkout.paystack.com/abc123',
                'reference': order.order_number,
            }
            response = self._pay(order, email='ama@example.com')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn('checkout.paystack.com', response.data['authorization_url'])

        order.refresh_from_db()
        self.assertEqual(order.status, OnlineOrder.Status.AWAITING_PAYMENT)
        self.assertTrue(order.payment_reference)

    def test_the_reference_sent_is_ours(self):
        """
        It is what comes back on the webhook, so it has to name the
        order without a lookup table in between.
        """
        from unittest.mock import patch

        order = self._order()
        with patch('apps.storefront.services.paystack.initialise') as init:
            init.return_value = {'success': True, 'authorization_url': 'https://x/y',
                                 'reference': order.order_number}
            self._pay(order, email='ama@example.com')

        sent = init.call_args.kwargs
        self.assertEqual(sent['reference'], order.order_number)
        # Paystack takes the smallest unit — pesewas.
        self.assertEqual(sent['amount_minor'], 56875)

    def test_an_empty_order_cannot_be_paid_for(self):
        order = self._order(total='0.00')
        response = self._pay(order, email='ama@example.com')
        self.assertEqual(response.status_code, 400)

    def test_an_order_with_nobody_on_it_cannot_be_paid_for(self):
        order = self._order(with_lead=False)
        response = self._pay(order, email='ama@example.com')
        self.assertEqual(response.status_code, 400)

    def test_an_order_already_paid_is_not_sent_again(self):
        from django.utils import timezone

        order = self._order()
        order.status = OnlineOrder.Status.PAID
        order.paid_at = timezone.now()
        order.save()

        response = self._pay(order, email='ama@example.com')
        self.assertEqual(response.status_code, 409)

    def test_a_refusal_from_paystack_leaves_the_order_alone(self):
        """
        Their outage is not our order's problem. It stays as it was and
        the customer can try again.
        """
        from unittest.mock import patch

        order = self._order()
        with patch('apps.storefront.services.paystack.initialise') as init:
            init.return_value = {'success': False, 'error': 'Service unavailable'}
            response = self._pay(order, email='ama@example.com')

        self.assertEqual(response.status_code, 502)
        order.refresh_from_db()
        self.assertEqual(order.status, OnlineOrder.Status.DRAFT)

    def _service_needing_a_file(self):
        from apps.jobs.models import Service, PricingRule
        service = Service.objects.create(
            name='Pay Flexy', code='PAYFLEXY',
            category='PRODUCTION', unit='PER_SQFT',
            requires_design=False, requires_file_upload=True, is_active=True,
        )
        PricingRule.objects.create(
            service=service, branch=None,
            base_price=Decimal('3.25'), color_multiplier=Decimal('1.00'),
            minimum_price=Decimal('10.00'), is_active=True,
        )
        return service

    def _order_for(self, service, specs=None):
        from rest_framework.test import APIClient
        client = APIClient()
        created = client.post('/api/v1/storefront/orders/', {}, format='json').data
        client.patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {
                'token': created['access_token'],
                'line_items': [{
                    'service': service.id, 'quantity': 1,
                    'specifications': specs or {'width_in': 72, 'height_in': 36},
                }],
            },
            format='json',
        )
        order = OnlineOrder.objects.get(order_number=created['order_number'])
        order.lead = Lead.objects.create(phone='0244777900', first_name='Ama')
        # Payment needs somewhere to make the job. These tests are about
        # what happens at Paystack, not about routing, so the branch is
        # set directly rather than chosen.
        order.branch = self.branch
        order.save()
        return order

    def test_a_job_needing_artwork_cannot_be_paid_for_without_it(self):
        """
        A branch cannot print what it has not been sent. Letting this
        through means an order arrives on the floor with nothing on it,
        and the money already taken.
        """
        order = self._order_for(self._service_needing_a_file())
        response = self._pay(order, email='ama@example.com')

        self.assertEqual(response.status_code, 400)
        self.assertIn('artwork', response.data['detail'].lower())

    def test_a_refused_file_does_not_count_as_artwork(self):
        """A file we have already said we cannot print is not a file."""
        from apps.storefront.models import OrderFile

        order = self._order_for(self._service_needing_a_file())
        OrderFile.objects.create(
            order=order, original_filename='screenshot.jpg',
            content_type='image/jpeg', verdict='refuse',
        )
        response = self._pay(order, email='ama@example.com')
        self.assertEqual(response.status_code, 400)

    def test_an_accepted_warning_is_enough_to_pay(self):
        """
        Warn proceeds. The customer was told it would print softly and
        said carry on, and that acceptance is on the record.
        """
        from unittest.mock import patch
        from apps.storefront.models import OrderFile

        order = self._order_for(self._service_needing_a_file())
        OrderFile.objects.create(
            order=order, original_filename='soft.jpg',
            content_type='image/jpeg', verdict='warn', warning_accepted=True,
        )
        with patch('apps.storefront.services.paystack.initialise') as init:
            init.return_value = {'success': True, 'authorization_url': 'https://x/y',
                                 'reference': order.order_number}
            response = self._pay(order, email='ama@example.com')

        self.assertEqual(response.status_code, 200, response.content)

    def test_a_service_needing_no_file_is_unaffected(self):
        """Photocopying brings its own paper to the counter."""
        from unittest.mock import patch
        from apps.jobs.models import Service, PricingRule

        service = Service.objects.create(
            name='Pay Typing', code='PAYTYPE',
            category='INSTANT', unit='PER_PAGE',
            requires_design=False, requires_file_upload=False, is_active=True,
        )
        PricingRule.objects.create(
            service=service, branch=None,
            base_price=Decimal('20.00'), color_multiplier=Decimal('1.00'),
            is_active=True,
        )
        order = self._order_for(service, specs={'pages': 5})

        with patch('apps.storefront.services.paystack.initialise') as init:
            init.return_value = {'success': True, 'authorization_url': 'https://x/y',
                                 'reference': order.order_number}
            response = self._pay(order, email='ama@example.com')

        self.assertEqual(response.status_code, 200, response.content)

    def test_an_order_with_no_branch_cannot_be_paid_for(self):
        """
        A job has to be made somewhere. Taking the money first means an
        order that belongs to no floor and a customer already charged.
        """
        from apps.jobs.models import Service, PricingRule

        service = Service.objects.create(
            name='Pay Nowhere', code='PAYNOWHERE',
            category='INSTANT', unit='PER_PAGE', is_active=True,
        )
        PricingRule.objects.create(
            service=service, branch=None, base_price=Decimal('20.00'),
            color_multiplier=Decimal('1.00'), is_active=True,
        )
        order = self._order_for(service, specs={'pages': 5})
        order.branch = None
        order.save()

        response = self._pay(order, email='ama@example.com')
        self.assertEqual(response.status_code, 400)
        self.assertIn('where', response.data['detail'].lower())

    @classmethod
    def setUpTestData(cls):
        import datetime
        from apps.organization.models import Branch

        cls.branch = Branch.objects.create(
            name='Pay Branch', code='PYB',
            is_headquarters=False, is_regional_hq=False,
            address='1 Pay Road',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30), closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )
    
    def test_the_paystack_module_imports(self):
        """
        Every other test mocks initialise, so the module's own imports
        never run. Without this, a missing dependency would be found by
        the first customer rather than here.
        """
        from apps.storefront.services import paystack
        self.assertTrue(callable(paystack.initialise))
        self.assertTrue(callable(paystack.verify))

class OrderFileTests(TestCase):
    """
    Artwork arriving before there is a job to attach it to.

    The checks need the ordered size: the same file is good artwork on a
    business card and unusable on a six-foot banner. So a file is judged
    against the line it belongs to, and judged again when that line
    changes — resizing a banner can turn a fine file into a refused one.
    """

    @classmethod
    def setUpTestData(cls):
        import datetime
        from apps.organization.models import Branch
        from apps.jobs.models import Service, PricingRule

        cls.branch = Branch.objects.create(
            name='File Branch', code='FLB',
            is_headquarters=False, is_regional_hq=False,
            address='1 File Road',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30), closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )
        cls.flexy = Service.objects.create(
            name='File Flexy', code='FLFLEXY',
            category='PRODUCTION', unit='PER_SQFT',
            requires_design=False, requires_file_upload=True, is_active=True,
            spec_template=[
                {'key': 'width_in', 'label': 'Width', 'type': 'number',
                 'required': True, 'default': 72, 'min': 6, 'unit': 'in'},
                {'key': 'height_in', 'label': 'Height', 'type': 'number',
                 'required': True, 'default': 36, 'min': 6, 'unit': 'in'},
            ],
        )
        PricingRule.objects.create(
            service=cls.flexy, branch=None,
            base_price=Decimal('3.25'), color_multiplier=Decimal('1.00'),
            minimum_price=Decimal('10.00'), is_active=True,
        )

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _client(self):
        from rest_framework.test import APIClient
        return APIClient()

    def _order_with_line(self, width=72, height=36):
        client = self._client()
        created = client.post('/api/v1/storefront/orders/', {}, format='json').data
        client.patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {
                'token': created['access_token'],
                'line_items': [{
                    'service': self.flexy.id, 'quantity': 1,
                    'specifications': {'width_in': width, 'height_in': height},
                }],
            },
            format='json',
        )
        return created

    def _image(self, width_px, height_px, name='artwork.jpg'):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        buf = io.BytesIO()
        Image.new('RGB', (width_px, height_px), (200, 30, 30)).save(buf, 'JPEG')
        buf.seek(0)
        return SimpleUploadedFile(name, buf.read(), content_type='image/jpeg')

    def _upload(self, created, upload):
        return self._client().post(
            f"/api/v1/storefront/orders/{created['order_number']}/file/",
            {'token': created['access_token'], 'file': upload},
            format='multipart',
        )

    # ── Getting a file on ──────────────────────────────────────────

    def test_a_good_file_is_accepted_and_measured(self):
        created = self._order_with_line()
        response = self._upload(created, self._image(7200, 3600))

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data['verdict'], 'fine')
        self.assertEqual(response.data['width_px'], 7200)

    def test_uploading_needs_the_orders_token(self):
        created = self._order_with_line()
        response = self._client().post(
            f"/api/v1/storefront/orders/{created['order_number']}/file/",
            {'file': self._image(1200, 600)},
            format='multipart',
        )
        self.assertEqual(response.status_code, 404)

    # ── The verdicts ───────────────────────────────────────────────

    def test_a_screenshot_on_a_banner_is_refused(self):
        """
        The case these checks exist for. 1080px across six feet is 15
        dpi, and nobody should be printing it.
        """
        created = self._order_with_line(width=72, height=36)
        response = self._upload(created, self._image(1080, 540))

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data['verdict'], 'refuse')

    def test_every_check_comes_back_not_just_the_failing_one(self):
        created = self._order_with_line()
        response = self._upload(created, self._image(1080, 540))

        names = {c['name'] for c in response.data['checks']}
        self.assertIn('readable', names)
        self.assertIn('resolution', names)
        for check in response.data['checks']:
            self.assertTrue(check['message'])

    def test_a_format_we_cannot_print_is_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        created = self._order_with_line()
        bad = SimpleUploadedFile('logo.cdr', b'not really a drawing',
                                 content_type='application/x-coreldraw')
        response = self._upload(created, bad)

        self.assertEqual(response.data['verdict'], 'refuse')
        self.assertIn('pdf', response.data['checks'][0]['message'].lower())

    # ── Judged again when the size changes ─────────────────────────

    def test_the_same_file_is_rejudged_when_the_banner_grows(self):
        """
        A file that was fine at card size is not fine at six feet. The
        verdict belongs to the pairing, not to the file.
        """
        created = self._order_with_line(width=6, height=4)
        first = self._upload(created, self._image(1800, 1200))
        self.assertEqual(first.data['verdict'], 'fine')

        client = self._client()
        client.patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {
                'token': created['access_token'],
                'line_items': [{
                    'service': self.flexy.id, 'quantity': 1,
                    'specifications': {'width_in': 144, 'height_in': 96},
                }],
            },
            format='json',
        )

        again = self._client().get(
            f"/api/v1/storefront/orders/{created['order_number']}/file/",
            {'token': created['access_token']},
        )
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(again.data['verdict'], 'refuse')

    # ── Replacing one ──────────────────────────────────────────────

    def test_a_second_upload_replaces_the_first(self):
        """
        A customer who sends better artwork has one file on the order,
        not two. The floor should never have to guess which to print.
        """
        from apps.storefront.models import OrderFile

        created = self._order_with_line()
        self._upload(created, self._image(1080, 540))
        self._upload(created, self._image(7200, 3600))

        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertEqual(OrderFile.objects.filter(order=order).count(), 1)
        self.assertEqual(order.files.first().width_px, 7200)

class BranchOptionsTests(TestCase):
    """
    Where this order could be made, and when each branch would finish.

    The customer chooses. Two branches, one ready at four across town
    and one tomorrow round the corner — only they know which matters,
    so both travel with the answer and neither is picked for them.
    """

    @classmethod
    def setUpTestData(cls):
        import datetime
        from apps.organization.models import Branch
        from apps.jobs.models import Service, PricingRule
        from apps.production.models import (
            Machine, MachineType, ServiceStation, Station,
        )

        cls.branch = Branch.objects.create(
            name='Options Branch', code='OPB',
            is_headquarters=False, is_regional_hq=False,
            address='1 Options Road',
            capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30), closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'),
            nhil_rate=Decimal('0'), getfund_rate=Decimal('0'),
        )

        cls.print_st = Station.objects.create(
            code='PRINT', name='Printing', sequence=1,
        )
        cls.large = MachineType.objects.create(
            code='LARGE_FORMAT', name='Large format printer',
            station=cls.print_st,
        )
        cls.machine = Machine.objects.create(
            branch=cls.branch, machine_type=cls.large,
            name='Options printer', max_width_mm=1900,
            is_active=True, is_available=True,
        )

        cls.flexy = Service.objects.create(
            name='Options Flexy', code='OPFLEXY',
            category='PRODUCTION', unit='PER_SQFT',
            requires_file_upload=False, is_active=True,
        )
        ServiceStation.objects.create(
            service=cls.flexy, station=cls.print_st, machine_type=cls.large,
            sequence=1, setup_minutes=Decimal('12'),
            minutes_per_unit=Decimal('0.143'),
        )
        PricingRule.objects.create(
            service=cls.flexy, branch=None,
            base_price=Decimal('3.25'), color_multiplier=Decimal('1.00'),
            minimum_price=Decimal('10.00'), is_active=True,
        )

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _client(self):
        from rest_framework.test import APIClient
        return APIClient()

    def _order(self, width=72, height=36):
        client = self._client()
        created = client.post(
            '/api/v1/storefront/orders/', {}, format='json',
        ).data
        client.patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {
                'token': created['access_token'],
                'line_items': [{
                    'service': self.flexy.id, 'quantity': 1,
                    'specifications': {'width_in': width, 'height_in': height},
                }],
            },
            format='json',
        )
        return created

    def _options(self, created, **params):
        query = {'token': created['access_token'], **params}
        return self._client().get(
            f"/api/v1/storefront/orders/{created['order_number']}/branches/",
            query,
        )

    # ── The answer ─────────────────────────────────────────────────

    def test_a_branch_that_can_do_it_comes_back_with_a_time(self):
        created = self._order()
        response = self._options(created)

        self.assertEqual(response.status_code, 200, response.content)
        option = response.data['options'][0]
        self.assertEqual(option['branch_code'], 'OPB')
        self.assertTrue(option['ready_at'])
        self.assertIn(option['confidence'], ('estimated', 'measured'))

    def test_an_order_with_nothing_on_it_is_refused(self):
        client = self._client()
        created = client.post(
            '/api/v1/storefront/orders/', {}, format='json',
        ).data
        response = self._options(created)
        self.assertEqual(response.status_code, 400)

    def test_the_token_is_required(self):
        created = self._order()
        response = self._client().get(
            f"/api/v1/storefront/orders/{created['order_number']}/branches/",
        )
        self.assertEqual(response.status_code, 404)

    # ── Which side goes across the roll ────────────────────────────

    def test_a_long_banner_fits_because_the_short_side_crosses_the_roll(self):
        """
        A 168 × 36 banner is not 168 inches wide on the machine. It is
        fed with the 36-inch side across the roll and the length runs
        off it. Reading the larger number would refuse nearly every
        banner we sell.
        """
        created = self._order(width=168, height=36)
        response = self._options(created)

        self.assertEqual(len(response.data['options']), 1)

    def test_a_banner_too_wide_on_both_sides_is_refused(self):
        """
        90 × 90 inches is 2286mm whichever way it is fed, and the
        machine takes 1900mm.
        """
        created = self._order(width=90, height=90)
        response = self._options(created)

        self.assertEqual(response.data['options'], [])
        self.assertTrue(response.data['refusals'])

    def test_a_refusal_says_what_would_fit(self):
        """
        A customer told only 'no' changes nothing. One told the machine
        takes 1900mm can resize.
        """
        created = self._order(width=90, height=90)
        response = self._options(created)

        reason = response.data['refusals'][0]['reason']
        self.assertIn('1900', reason)

    # ── Nothing available ──────────────────────────────────────────

    def test_a_machine_down_leaves_no_options_but_explains_itself(self):
        created = self._order()
        self.machine.is_available = False
        self.machine.save()

        response = self._options(created)
        self.assertEqual(response.data['options'], [])
        self.assertIn('service', response.data['refusals'][0]['reason'].lower())
        # ── Keeping the choice ─────────────────────────────────────────

    def test_the_chosen_branch_is_kept_on_the_order(self):
        """
        The customer's pick has to survive the page. Without it the job
        reaches conversion with nowhere to be made.
        """
        created = self._order()
        response = self._client().patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {'token': created['access_token'], 'branch': self.branch.id},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertEqual(order.branch_id, self.branch.id)

    def test_a_branch_that_cannot_do_the_work_is_refused(self):
        """
        Not merely absent from the list: a pick is checked again on the
        way in. The options were right when they were drawn, and a
        machine can go down between then and the tap.
        """
        created = self._order()
        self.machine.is_available = False
        self.machine.save()

        response = self._client().patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {'token': created['access_token'], 'branch': self.branch.id},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_an_unknown_branch_is_refused(self):
        created = self._order()
        response = self._client().patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {'token': created['access_token'], 'branch': 999999},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_changing_the_size_clears_the_chosen_branch(self):
        """
        A branch that could make a 36-inch banner may not be able to
        make a 90-inch one. The pick was made against the old size and
        cannot be assumed to hold.
        """
        created = self._order()
        client = self._client()
        client.patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {'token': created['access_token'], 'branch': self.branch.id},
            format='json',
        )

        client.patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {
                'token': created['access_token'],
                'line_items': [{
                    'service': self.flexy.id, 'quantity': 1,
                    'specifications': {'width_in': 90, 'height_in': 90},
                }],
            },
            format='json',
        )

        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertIsNone(order.branch_id)

class CartTests(TestCase):
    """
    More than one thing in an order.

    A church ordering a banner, flyers and programmes together is a
    better customer than one buying a banner — and it is how a print
    shop is actually used. Each line carries its own artwork, because a
    banner's file is not the flyer's.

    Lines need stable ids for that. Position in a list is not an
    identity: removing the first line would silently hand its artwork
    to the second.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.jobs.models import Service, PricingRule

        cls.flexy = Service.objects.create(
            name='Cart Flexy', code='CARTFLEXY',
            category='PRODUCTION', unit='PER_SQFT',
            requires_file_upload=True, is_active=True,
        )
        PricingRule.objects.create(
            service=cls.flexy, branch=None, base_price=Decimal('3.25'),
            color_multiplier=Decimal('1.00'), minimum_price=Decimal('10.00'),
            is_active=True,
        )

        cls.cards = Service.objects.create(
            name='Cart Cards', code='CARTCARDS',
            category='PRODUCTION', unit='PER_PIECE',
            requires_file_upload=True, is_active=True,
        )
        PricingRule.objects.create(
            service=cls.cards, branch=None, base_price=Decimal('1.50'),
            color_multiplier=Decimal('1.00'), is_active=True,
        )

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _client(self):
        from rest_framework.test import APIClient
        return APIClient()

    def _order(self):
        return self._client().post(
            '/api/v1/storefront/orders/', {}, format='json',
        ).data

    def _put_lines(self, created, lines):
        return self._client().patch(
            f"/api/v1/storefront/orders/{created['order_number']}/",
            {'token': created['access_token'], 'line_items': lines},
            format='json',
        )

    def _image(self, width_px=3000, height_px=1500, name='art.jpg'):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        buf = io.BytesIO()
        Image.new('RGB', (width_px, height_px), (30, 90, 200)).save(buf, 'JPEG')
        buf.seek(0)
        return SimpleUploadedFile(name, buf.read(), content_type='image/jpeg')

    def _upload(self, created, line_id, upload):
        return self._client().post(
            f"/api/v1/storefront/orders/{created['order_number']}/file/",
            {
                'token': created['access_token'],
                'line_id': line_id,
                'file': upload,
            },
            format='multipart',
        )

    # ── Lines have identities ──────────────────────────────────────

    def test_every_line_comes_back_with_an_id(self):
        created = self._order()
        response = self._put_lines(created, [
            {'service': self.flexy.id, 'quantity': 1,
             'specifications': {'width_in': 72, 'height_in': 36}},
            {'service': self.cards.id, 'quantity': 100, 'specifications': {}},
        ])

        self.assertEqual(response.status_code, 200, response.content)
        ids = [line['id'] for line in response.data['line_items']]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)

    def test_an_id_survives_a_repricing(self):
        """
        Changing one line must not renumber the others, or their
        artwork would follow the wrong item.
        """
        created = self._order()
        first = self._put_lines(created, [
            {'service': self.flexy.id, 'quantity': 1,
             'specifications': {'width_in': 72, 'height_in': 36}},
        ]).data['line_items'][0]

        again = self._put_lines(created, [
            {'id': first['id'], 'service': self.flexy.id, 'quantity': 2,
             'specifications': {'width_in': 72, 'height_in': 36}},
        ]).data['line_items'][0]

        self.assertEqual(again['id'], first['id'])
        self.assertEqual(again['quantity'], 2)

    # ── Artwork belongs to a line ──────────────────────────────────

    def test_each_line_carries_its_own_artwork(self):
        created = self._order()
        lines = self._put_lines(created, [
            {'service': self.flexy.id, 'quantity': 1,
             'specifications': {'width_in': 72, 'height_in': 36}},
            {'service': self.cards.id, 'quantity': 100, 'specifications': {}},
        ]).data['line_items']

        banner = self._upload(created, lines[0]['id'], self._image(name='banner.jpg'))
        cards = self._upload(created, lines[1]['id'], self._image(name='cards.jpg'))

        self.assertEqual(banner.status_code, 201, banner.content)
        self.assertEqual(cards.status_code, 201, cards.content)

        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertEqual(order.files.count(), 2)

    def test_replacing_one_line_s_artwork_leaves_the_other_alone(self):
        """
        One file per line, not one per order. A customer sending better
        artwork for the banner has not withdrawn the flyer's.
        """
        created = self._order()
        lines = self._put_lines(created, [
            {'service': self.flexy.id, 'quantity': 1,
             'specifications': {'width_in': 72, 'height_in': 36}},
            {'service': self.cards.id, 'quantity': 100, 'specifications': {}},
        ]).data['line_items']

        self._upload(created, lines[0]['id'], self._image(name='banner.jpg'))
        self._upload(created, lines[1]['id'], self._image(name='cards.jpg'))
        self._upload(created, lines[0]['id'], self._image(name='banner-v2.jpg'))

        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertEqual(order.files.count(), 2)
        # Storage adds a suffix when a name is already taken on disk, so
        # the stems are what matter rather than the exact filenames.
        names = [f.original_filename for f in order.files.all()]
        self.assertTrue(any(n.startswith('banner-v2') for n in names), names)
        self.assertTrue(any(n.startswith('cards') for n in names), names)
        self.assertFalse(any(n.startswith('banner.') for n in names), names)

    def test_a_file_is_judged_against_its_own_line(self):
        """
        1500px is fine across a business card and hopeless across six
        feet. The verdict belongs to the pairing.
        """
        created = self._order()
        lines = self._put_lines(created, [
            {'service': self.flexy.id, 'quantity': 1,
             'specifications': {'width_in': 144, 'height_in': 72}},
            {'service': self.cards.id, 'quantity': 100, 'specifications': {}},
        ]).data['line_items']

        on_banner = self._upload(created, lines[0]['id'], self._image(1500, 750))
        self.assertEqual(on_banner.data['verdict'], 'refuse')

    def test_removing_a_line_removes_its_artwork(self):
        """
        Nothing should be left pointing at a line that is gone, least
        of all a file the floor might print.
        """
        created = self._order()
        lines = self._put_lines(created, [
            {'service': self.flexy.id, 'quantity': 1,
             'specifications': {'width_in': 72, 'height_in': 36}},
            {'service': self.cards.id, 'quantity': 100, 'specifications': {}},
        ]).data['line_items']

        self._upload(created, lines[0]['id'], self._image(name='banner.jpg'))
        self._upload(created, lines[1]['id'], self._image(name='cards.jpg'))

        self._put_lines(created, [
            {'id': lines[1]['id'], 'service': self.cards.id,
             'quantity': 100, 'specifications': {}},
        ])

        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertEqual(order.files.count(), 1)
        self.assertTrue(
            order.files.first().original_filename.startswith('cards'),
            order.files.first().original_filename,
        )

    # ── Paying for several things ──────────────────────────────────

    def test_every_line_that_needs_artwork_must_have_it(self):
        from apps.storefront.views import _artwork_missing

        created = self._order()
        lines = self._put_lines(created, [
            {'service': self.flexy.id, 'quantity': 1,
             'specifications': {'width_in': 72, 'height_in': 36}},
            {'service': self.cards.id, 'quantity': 100, 'specifications': {}},
        ]).data['line_items']

        self._upload(created, lines[0]['id'], self._image(name='banner.jpg'))

        order = OnlineOrder.objects.get(order_number=created['order_number'])
        self.assertIsNotNone(_artwork_missing(order))

class ArtworkCheckTests(TestCase):
    """
    Judging a file before anything is committed.

    The check has to happen while the customer can still act on it —
    before they press Continue, not after. But nothing should exist on
    the server at that point, so the verdict cannot be stored against
    an order.

    So the verdict comes back signed, carrying what it was judged
    against: the file's hash, the service, the size. The commit
    verifies it. A verdict the browser edited, or one for a different
    file, is worthless — which is what stops a customer uploading good
    artwork, getting a pass, and committing something else.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.jobs.models import Service, PricingRule

        cls.flexy = Service.objects.create(
            name='Check Flexy', code='CHKFLEXY',
            category='PRODUCTION', unit='PER_SQFT',
            requires_file_upload=True, is_active=True,
            spec_template=[
                {'key': 'width_in', 'label': 'Width', 'type': 'number',
                 'required': True, 'min': 6, 'unit': 'in'},
                {'key': 'height_in', 'label': 'Height', 'type': 'number',
                 'required': True, 'min': 6, 'unit': 'in'},
            ],
        )
        PricingRule.objects.create(
            service=cls.flexy, branch=None, base_price=Decimal('3.25'),
            color_multiplier=Decimal('1.00'), minimum_price=Decimal('10.00'),
            is_active=True,
        )

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _client(self):
        from rest_framework.test import APIClient
        return APIClient()

    def _image(self, width_px=11000, height_px=5500, name='art.jpg'):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        buf = io.BytesIO()
        Image.new('RGB', (width_px, height_px), (10, 80, 160)).save(buf, 'JPEG')
        buf.seek(0)
        return SimpleUploadedFile(name, buf.read(), content_type='image/jpeg')

    def _check(self, upload, width=72, height=36, service=None):
        return self._client().post(
            '/api/v1/storefront/check/',
            {
                'file': upload,
                'service': (service or self.flexy).id,
                'specifications': json.dumps({
                    'width_in': width, 'height_in': height,
                }),
            },
            format='multipart',
        )

    # ── Judging without committing ─────────────────────────────────

    def test_a_file_is_judged_with_no_order_in_existence(self):
        before = OnlineOrder.objects.count()
        response = self._check(self._image())

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['verdict'], 'fine')
        self.assertEqual(OnlineOrder.objects.count(), before)

    def test_a_check_commits_nothing(self):
        """
        No order, no line, no artwork on an order. The file itself is
        kept so the customer need not send it twice, but it belongs to
        nothing and is swept within hours.
        """
        from apps.storefront.models import OrderFile, StagedUpload

        orders = OnlineOrder.objects.count()
        files = OrderFile.objects.count()

        self._check(self._image())

        self.assertEqual(OnlineOrder.objects.count(), orders)
        self.assertEqual(OrderFile.objects.count(), files)
        self.assertEqual(StagedUpload.objects.count(), 1)

    def test_a_poor_file_is_refused_with_its_reasons(self):
        response = self._check(self._image(1000, 500), width=144, height=72)

        self.assertEqual(response.data['verdict'], 'refuse')
        self.assertTrue(response.data['checks'])
        self.assertTrue(
            any('dpi' in c['message'].lower() for c in response.data['checks'])
        )

    def test_the_same_file_is_judged_against_the_size_given(self):
        """
        1000px is fine on a small print and hopeless across twelve feet.
        The verdict belongs to the pairing, so the size travels with the
        request.
        """
        # 4000 × 2000 is 333 dpi across 12 inches and 28 dpi across
        # twelve feet. One file, two verdicts, because the verdict
        # belongs to the pairing.
        small = self._check(self._image(4000, 2000), width=12, height=6)
        large = self._check(self._image(4000, 2000), width=144, height=72)

        self.assertEqual(small.data['verdict'], 'fine')
        self.assertEqual(large.data['verdict'], 'refuse')

    # ── The token ──────────────────────────────────────────────────

    def test_a_passing_check_returns_a_token(self):
        response = self._check(self._image())
        self.assertTrue(response.data['token'])

    def test_a_refused_check_returns_no_token(self):
        """
        Nothing to carry forward. A refused file has no commit to
        authorise.
        """
        response = self._check(self._image(1000, 500), width=144, height=72)
        self.assertIsNone(response.data.get('token'))

    def test_the_token_names_what_it_judged(self):
        from apps.storefront.services.verdicts import read_token

        # Large enough to pass at 96 inches — a token only comes back
        # for a file we would print.
        response = self._check(self._image(9600, 4800), width=96, height=48)
        self.assertEqual(response.data['verdict'], 'fine')
        claim = read_token(response.data['token'])

        self.assertEqual(claim['service'], self.flexy.id)
        self.assertEqual(claim['specifications']['width_in'], 96)
        self.assertEqual(claim['verdict'], 'fine')
        self.assertTrue(claim['file_hash'])

    def test_a_tampered_token_is_refused(self):
        """
        The signature is what makes the claim worth anything. Without
        it the browser could assert any verdict it liked.
        """
        from apps.storefront.services.verdicts import read_token

        response = self._check(self._image())
        token = response.data['token']
        self.assertIsNone(read_token(token[:-4] + 'aaaa'))

    def test_a_stale_token_is_refused(self):
        from apps.storefront.services.verdicts import read_token, sign_claim

        token = sign_claim(
            {'service': self.flexy.id, 'verdict': 'fine', 'file_hash': 'abc'},
            age_seconds=-10,
        )
        self.assertIsNone(read_token(token))

    # ── Not a door into the system ─────────────────────────────────

    def test_an_unknown_service_is_refused(self):
        response = self._client().post(
            '/api/v1/storefront/check/',
            {'file': self._image(), 'service': 999999,
             'specifications': json.dumps({})},
            format='multipart',
        )
        self.assertEqual(response.status_code, 400)

    def test_a_file_that_is_not_one_we_print_is_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        bad = SimpleUploadedFile('logo.cdr', b'not a drawing',
                                 content_type='application/x-coreldraw')
        response = self._check(bad)
        self.assertEqual(response.data['verdict'], 'refuse')