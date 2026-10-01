from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.storefront.models import Lead, OnlineOrder


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