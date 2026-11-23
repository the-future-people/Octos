"""
Farhat Trade Partners, part two (23 Nov 2026): what a partner pays, the
rewards, and a partner's paid order becoming a plain-packed job for its
business.
"""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.customers.models import CustomerProfile
from apps.finance.models import DailySalesSheet
from apps.jobs.models import PricingRule, Service
from apps.organization.models import Branch
from apps.partners.models import Partner, PartnerRep
from apps.partners.services import pricing
from apps.storefront.models import Lead, OnlineOrder

CODE = 'apps.storefront.services.accounts.secrets.randbelow'


def line(total, at_minimum=False, service=None, line_id='l1'):
    return {'id': line_id, 'service': service, 'service_name': 'Flexy Banner', 'quantity': 1,
            'specifications': {'width_in': 72, 'height_in': 36}, 'total': str(total),
            'at_minimum': at_minimum}


class Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(
            name='Trade Branch', code='TRB', is_headquarters=False, is_regional_hq=False,
            address='1 Trade Road', capacity_score=100, current_load=0, is_active=True,
            opening_time=datetime.time(7, 30), closing_time=datetime.time(19, 30),
            vat_registered=False, vat_rate=Decimal('0'), nhil_rate=Decimal('0'), getfund_rate=Decimal('0'))
        cls.flexy = Service.objects.create(name='Trade Flexy', code='TRFLX', category='PRODUCTION',
                                           unit='PER_SQFT', requires_file_upload=True, is_active=True, online=True)
        PricingRule.objects.create(service=cls.flexy, branch=None, base_price=Decimal('3.25'),
                                   color_multiplier=Decimal('1.00'), minimum_price=Decimal('30.00'),
                                   is_active=True)
        cls.business = CustomerProfile.objects.create(phone='+233244550912', first_name='Kobby Prints',
                                                      company_name='Kobby Prints', customer_type='BUSINESS')
        cls.partner = Partner.objects.create(
            code='MAD-K7Q2', status=Partner.Status.APPROVED, name='Kobby Prints', kind='PRINT_SHOP',
            shop_photo='partners/shop.png', logo='partners/logo.png', region='Greater Accra', area='Madina',
            gps_address='GA-402-1187', landmark='the junction', primary_phone='+233244550912',
            monthly_volume='6-20', terms_version='2026-11-23', terms_accepted_at=timezone.now(),
            customer=cls.business, decided_at=timezone.now())
        cls.lead = Lead.objects.create(phone='+233201112233', first_name='Kobby')
        PartnerRep.objects.create(partner=cls.partner, lead=cls.lead, title='Mr', first_name='Kobby',
                                  last_name='Asante', role='OWNER')

    def order(self, *lines, **extra):
        return OnlineOrder.objects.create(lead=self.lead, partner=self.partner, partner_reference='Mensah banner',
                                          line_items=list(lines), **extra)

    def paid(self, total='50.00', fee='0.00'):
        """A finished partner job, counted toward the milestones when worth GHS 30+."""
        o = OnlineOrder.objects.create(lead=self.lead, partner=self.partner, line_items=[line(total)])
        OnlineOrder.objects.filter(pk=o.pk).update(status=OnlineOrder.Status.CONVERTED, paid_at=timezone.now(),
                                                   total=Decimal(total), processing_fee=Decimal(fee))
        return o


class PricingTests(Base):

    def test_the_first_job_is_ten_percent_off_plus_the_fee(self):
        order = self.order(line('50.00'))
        self.assertEqual(order.full_total, Decimal('50.00'))
        self.assertEqual(order.discount_amount, Decimal('5.00'))
        self.assertEqual(order.partner_reward, pricing.FIRST)
        self.assertEqual(order.discount_reason, 'Trade partner first job, 10% off')
        # The fee is grossed up: after Paystack's 1.95%, Farhat keeps the 45.00.
        self.assertEqual(order.processing_fee, Decimal('0.90'))
        self.assertEqual(order.total, Decimal('45.90'))

    def test_after_that_six_percent_under_walk_in(self):
        self.paid()
        order = self.order(line('50.00'))
        self.assertEqual(order.discount_amount, Decimal('3.00'))      # GHS 47 where a walk-in pays 50
        self.assertEqual(order.partner_reward, '')
        self.assertEqual(order.discount_reason, 'Trade price, 6% off')

    def test_one_job_in_every_twenty_is_ten_percent_off(self):
        for _ in range(20):
            self.paid()
        order = self.order(line('100.00'))
        self.assertEqual((order.discount_amount, order.partner_reward), (Decimal('10.00'), pricing.EVERY_20))
        self.paid()
        self.assertEqual(self.order(line('100.00')).discount_amount, Decimal('6.00'))

    def test_small_jobs_dont_count_toward_the_twenty(self):
        self.paid()
        for _ in range(19):
            self.paid(total='29.00')
        self.assertEqual(pricing.counted_jobs(self.partner), 1)

    def test_nothing_comes_off_a_line_at_its_minimum_charge(self):
        self.paid()
        order = self.order(line('30.00', at_minimum=True, line_id='a'), line('100.00', line_id='b'))
        self.assertEqual(order.full_total, Decimal('130.00'))
        self.assertEqual(order.discount_amount, Decimal('6.00'))

    def test_a_paid_order_is_frozen(self):
        order = self.order(line('50.00'))
        OnlineOrder.objects.filter(pk=order.pk).update(status=OnlineOrder.Status.PAID, paid_at=timezone.now())
        order.refresh_from_db()
        order.line_items = [line('500.00')]
        order.save()
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal('45.90'))

    def test_a_retail_order_is_untouched(self):
        retail = OnlineOrder.objects.create(lead=self.lead, line_items=[line('50.00')], total=Decimal('50.00'))
        self.assertEqual((retail.total, retail.processing_fee, retail.discount_amount),
                         (Decimal('50.00'), Decimal('0'), Decimal('0')))

    def test_no_customer_code_discount_on_top(self):
        self.paid()
        order = self.order(line('200.00'))
        with patch('apps.storefront.views.send_sms'):
            r = APIClient().post(f'/api/v1/storefront/orders/{order.order_number}/code/',
                                 {'token': order.access_token})
        self.assertEqual(r.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.discount_amount, Decimal('12.00'))
        self.assertEqual(order.discount_reason, 'Trade price, 6% off')


class ConversionTests(Base):

    def test_a_partners_paid_order_is_its_businesss_job_packed_plain(self):
        from apps.storefront.services.conversion import convert
        DailySalesSheet.objects.get_or_create(branch=self.branch, date=timezone.localdate(),
                                              defaults={'status': DailySalesSheet.Status.OPEN})
        order = self.order(line('117.00', service=self.flexy.id), branch=self.branch)
        OnlineOrder.objects.filter(pk=order.pk).update(status=OnlineOrder.Status.PAID, paid_at=timezone.now(),
                                                       payment_reference='TRD-1')
        order.refresh_from_db()
        job = convert(order)
        self.assertEqual(job.customer_id, self.business.pk)          # the business, never the rep
        self.assertEqual(job.trade_partner_id, self.partner.pk)
        self.assertEqual(job.partner_reference, 'Mensah banner')
        self.assertEqual(job.discount_amount, order.discount_amount)
        self.assertEqual(job.estimated_cost, order.total)


class PortalTests(Base):

    def token(self):
        from apps.storefront.services import accounts
        with patch(CODE, return_value=222222):
            accounts.send_code(self.lead.phone)
        return accounts.verify_code(self.lead.phone, '222222')[1]

    def test_an_approved_partner_starts_an_order_and_sees_its_dashboard(self):
        client = APIClient()
        auth = {'HTTP_AUTHORIZATION': f'App {self.token()}'}
        r = client.post('/api/v1/partners/orders/', {'reference': '  Order 112,   church stickers '}, **auth)
        self.assertEqual(r.status_code, 201)
        order = OnlineOrder.objects.get(order_number=r.data['order_number'])
        self.assertEqual((order.partner_id, order.partner_reference), (self.partner.pk, 'Order 112, church stickers'))
        self.paid()
        me = client.get('/api/v1/partners/me/', **auth)
        self.assertEqual(me.data['code'], 'MAD·K7Q2')
        self.assertEqual(me.data['rewards']['jobs'], 1)
        self.assertEqual(me.data['rewards']['wrap'], {'at': 15, 'done': 1, 'earned': False})
        self.assertEqual(len(me.data['jobs']), 1)

    def test_a_paused_partner_cant_send_new_jobs(self):
        Partner.objects.filter(pk=self.partner.pk).update(status=Partner.Status.PAUSED)
        r = APIClient().post('/api/v1/partners/orders/', {'reference': 'x'},
                             HTTP_AUTHORIZATION=f'App {self.token()}')
        self.assertEqual(r.status_code, 403)
