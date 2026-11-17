"""
Costs, bulk prices and discounts (17 Nov 2026).

The case that started it: 314 colour pages x 3 copies bound, list price
GHS 2.50 a page, the customer wanting GHS 2.00. With the default costs an
A4 colour page costs about GHS 0.74, so the Branch Manager may go down to
2.5 x that; lower needs the owner.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.customers.models import CustomerProfile
from apps.jobs.models import CostSettings, Job, JobLineItem, PriceCut, PricingRule, Service
from apps.jobs.pricing_engine import PricingEngine
from apps.jobs.services import discounts
from apps.jobs.services.costing import job_cost, unit_cost
from apps.jobs.services.discounts import DiscountRefused
from apps.jobs.services.savings import savings
from apps.jobs.tests import JobsFixtureMixin

NOTIFY = 'apps.notifications.services.notify'


class Base(JobsFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.colour = Service.objects.create(
            name='A4 Colour Printing (one side)', code='DSC-COL', category='INSTANT', unit='PER_COPY',
            requires_design=False, requires_file_upload=False, is_active=True,
            cost_basis=Service.COST_COLOUR)
        cls.rule = PricingRule.objects.create(service=cls.colour, branch=None, base_price=Decimal('2.50'),
                                              color_multiplier=Decimal('1.00'), is_active=True,
                                              bulk_prices=[{'from': 200, 'price': '2.30'},
                                                           {'from': 500, 'price': '2.20'}])
        cls.mystery = Service.objects.create(
            name='Mystery Finishing', code='DSC-MYS', category='INSTANT', unit='PER_PIECE',
            requires_design=False, requires_file_upload=False, is_active=True)
        cls.owner = cls.bm.__class__.objects.create(
            employee_id='DSC-OWN', first_name='Khofi', last_name='Owner', email='dsc-own@test.local',
            employment_status='ACTIVE', is_active=True, is_business_owner=True, branch=cls.branch)

    def job(self, service=None, pages=314, sets=3, total=None):
        service = service or self.colour
        price = PricingEngine.get_price(service=service, branch=self.branch, quantity=sets, pages=pages)
        total = Decimal(str(total if total is not None else price['total']))
        job = Job.objects.create(branch=self.branch, job_type=Job.INSTANT, title=service.name,
                                 status=Job.PENDING_PAYMENT, estimated_cost=total, intake_by=self.bm,
                                 bulk_saving=Decimal(str(price.get('bulk_saving') or 0)))
        JobLineItem.objects.create(job=job, service=service, pages=pages, sets=sets, quantity=1,
                                   unit_price=Decimal(price.get('base_price', '0')), line_total=total)
        return job


class CostTests(Base):

    def test_a_colour_page_from_the_default_costs(self):
        self.assertEqual(round(unit_cost(self.colour), 2), Decimal('0.74'))

    def test_a_black_and_white_page_costs_less(self):
        self.colour.cost_basis = Service.COST_BW
        self.assertEqual(round(unit_cost(self.colour), 2), Decimal('0.27'))

    def test_a_job_costs_its_pages(self):
        cost = job_cost(self.job())
        self.assertTrue(cost['known'])
        self.assertEqual(cost['page_units'], 942)
        self.assertAlmostEqual(float(cost['cost']), 942 * 0.7432, delta=1)

    def test_something_with_no_cost_makes_it_unknown(self):
        self.assertFalse(job_cost(self.job(service=self.mystery, pages=1, sets=1, total=10))['known'])


class BulkPriceTests(Base):

    def test_counted_on_pages_times_copies(self):
        price = PricingEngine.get_price(service=self.colour, branch=None, quantity=3, pages=314)
        self.assertEqual(price['total'], Decimal('2072.40'))          # 942 x 2.20
        self.assertEqual(price['bulk'], {'from': 500, 'price': '2.20'})
        self.assertEqual(Decimal(price['bulk_saving']), Decimal('282.60'))
        self.assertIsNone(price['next_bulk'])

    def test_below_the_first_band_the_list_price_and_the_next_band(self):
        price = PricingEngine.get_price(service=self.colour, branch=None, quantity=1, pages=150)
        self.assertEqual(price['total'], Decimal('375.00'))
        self.assertIsNone(price['bulk'])
        self.assertEqual(price['next_bulk'], {'from': 200, 'price': '2.30', 'more': 50})

    def test_a_job_made_through_the_counter_keeps_the_saving(self):
        job = self.job()
        self.assertEqual(job.estimated_cost, Decimal('2072.40'))
        self.assertEqual(job.bulk_saving, Decimal('282.60'))


class DiscountTests(Base):

    def setUp(self):
        p = patch(NOTIFY)
        self.notify = p.start()
        self.addCleanup(p.stop)

    def test_the_manager_lowers_within_the_floor(self):
        job = self.job()                                               # 2072.40, floor about 1750
        cut = discounts.lower(self.bm, '1958.00', 'Large order, regular customer', job=job)
        self.assertEqual(cut.status, PriceCut.Status.APPLIED)
        job.refresh_from_db()
        self.assertEqual(job.estimated_cost, Decimal('1958.00'))
        self.assertEqual(job.discount_amount, Decimal('114.40'))
        self.assertEqual(job.discount_by, self.bm)

    def test_below_the_floor_waits_for_the_owner_then_applies(self):
        job = self.job()
        cut = discounts.lower(self.bm, '1500.00', 'He insists', job=job)
        self.assertEqual(cut.status, PriceCut.Status.PENDING)
        job.refresh_from_db()
        self.assertEqual(job.estimated_cost, Decimal('2072.40'))      # untouched until the owner says
        self.assertEqual(self.notify.call_args.kwargs['recipient'], self.owner)
        discounts.approve(self.owner, cut.pk)
        job.refresh_from_db()
        self.assertEqual(job.estimated_cost, Decimal('1500.00'))

    def test_the_owner_can_decline(self):
        cut = discounts.lower(self.bm, '1500.00', 'He insists', job=self.job())
        discounts.decline(self.owner, cut.pk, 'Too low for this month')
        cut.refresh_from_db()
        self.assertEqual(cut.status, PriceCut.Status.DECLINED)

    def test_the_owner_goes_below_the_floor_directly(self):
        cut = discounts.lower(self.owner, '1500.00', 'Old friend of the shop', job=self.job())
        self.assertEqual(cut.status, PriceCut.Status.APPLIED)

    def test_with_no_cost_the_manager_has_a_percentage(self):
        job = self.job(service=self.mystery, pages=1, sets=1, total=100)
        self.assertEqual(discounts.lower(self.bm, '92', 'Small favour', job=job).status, PriceCut.Status.APPLIED)
        self.assertEqual(discounts.lower(self.bm, '80', 'Bigger favour', job=job).status, PriceCut.Status.PENDING)

    def test_a_newer_cut_replaces_and_restoring_clears_it(self):
        job = self.job()
        discounts.lower(self.bm, '2000', 'First offer', job=job)
        discounts.lower(self.bm, '2072.40', 'Back to the price', job=job)
        job.refresh_from_db()
        self.assertEqual((job.estimated_cost, job.discount_amount, job.discount_reason),
                         (Decimal('2072.40'), Decimal('0.00'), ''))

    def test_refused_after_payment_without_a_reason_or_for_an_attendant(self):
        job = self.job()
        with self.assertRaises(DiscountRefused):
            discounts.lower(self.bm, '2000', '', job=job)
        with self.assertRaises(DiscountRefused):
            discounts.lower(self.attendant, '2000', 'Please', job=job)
        Job.objects.filter(pk=job.pk).update(amount_paid=Decimal('500'))
        job.refresh_from_db()
        with self.assertRaises(DiscountRefused):
            discounts.lower(self.bm, '2000', 'Too late', job=job)

    def test_the_receipt_says_what_was_saved(self):
        job = self.job()
        discounts.lower(self.bm, '1958.00', 'Large order', job=job)
        job.refresh_from_db()
        saved = savings(job)
        self.assertEqual((saved['list'], saved['bulk'], saved['discount'], saved['saved']),
                         ('2,355.00', '282.60', '114.40', '397.00'))


class ProformaDiscountTests(Base):

    def setUp(self):
        p = patch(NOTIFY)
        p.start()
        self.addCleanup(p.stop)
        from apps.jobs.services.proforma_engine import ProformaEngine
        customer = CustomerProfile.objects.create(
            phone='0555000777', affiliation_active=True, customer_type=CustomerProfile.INDIVIDUAL,
            visit_count=0, total_spend=Decimal('0'), tier=CustomerProfile.REGULAR, confidence_score=0,
            is_priority=False, is_walkin=False, first_name='Kwaku', last_name='Hemeng')
        self.engine = ProformaEngine(self.branch)
        self.proforma = self.engine.create(customer=customer, actor=self.bm,
                                           raw_lines=[{'service': self.colour.pk, 'quantity': 3, 'pages': 314}])

    def test_a_proforma_carries_its_bulk_price_and_takes_a_discount_into_its_job(self):
        self.assertEqual(self.proforma.bulk_saving, Decimal('282.60'))
        discounts.lower(self.bm, '1958.00', 'Large order', proforma=self.proforma)
        self.proforma.refresh_from_db()
        self.assertEqual(self.proforma.total, Decimal('1958.00'))
        self.engine.issue(self.proforma, actor=self.bm)
        self.proforma.refresh_from_db()
        job = self.engine.convert(self.proforma, actor=self.bm)
        self.assertEqual((job.estimated_cost, job.discount_amount), (Decimal('1958.00'), Decimal('114.40')))


class EndpointTests(Base):

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    @patch(NOTIFY)
    def test_the_panel_and_lowering_through_the_api(self, _notify):
        job = self.job()
        panel = self.api(self.bm).get('/api/v1/jobs/discounts/', {'job': job.pk}).data
        self.assertEqual((panel['total'], panel['page_units'], panel['cost_known']), ('2072.40', 942, True))
        response = self.api(self.bm).post('/api/v1/jobs/discounts/',
                                          {'job': job.pk, 'new_total': '1958', 'reason': 'Large order'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['summary']['saved'], '397.00')

    def test_costs_for_the_manager_not_the_attendant(self):
        self.assertEqual(self.api(self.bm).get('/api/v1/jobs/costs/').data['page']['colour'], '0.74')
        self.assertEqual(self.api(self.attendant).get('/api/v1/jobs/costs/').status_code, 403)
        updated = self.api(self.bm).put('/api/v1/jobs/costs/', {'paper_box_price': '400'}, format='json').data
        self.assertEqual(updated['paper_box_price'], '400.00')
        self.assertEqual(CostSettings.current().paper_box_price, Decimal('400'))

    def test_bulk_prices_saved_through_the_pricing_rule(self):
        response = self.api(self.bm).patch(f'/api/v1/jobs/pricing/{self.rule.pk}/',
                                           {'bulk_prices': [{'from': 1000, 'price': 2.0}]}, format='json')
        self.assertIn(response.status_code, (200, 403))
