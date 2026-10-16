"""
The catalogue as the storefront and the floor see it: what is available,
what can be added, how add-ons are priced, and how they travel from a
cart line into the job and onto the floor.
"""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.jobs.models import Job, JobLineItem, PricingRule, Service
from apps.jobs.pricing_engine import quote_line
from apps.jobs.services.availability import can_make, price_addons
from apps.jobs.services.steps import build_steps
from apps.jobs.tests import JobsFixtureMixin
from apps.production.models import Machine, MachineType, ServiceStation, Station


class CatalogueTests(JobsFixtureMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.print_st = Station.objects.create(code='PRINT', name='Printing', sequence=1)
        cls.lam_st   = Station.objects.create(code='LAMINATE', name='Laminating', sequence=3)
        cls.bind_st  = Station.objects.create(code='BIND', name='Binding', sequence=4)
        cls.fin_st   = Station.objects.create(code='FINISH', name='Hand finishing', sequence=5)

        press = MachineType.objects.create(code='DIGITAL_PRESS', name='Digital press', station=cls.print_st)
        laminator = MachineType.objects.create(code='LAMINATOR', name='Laminator', station=cls.lam_st)
        binder = MachineType.objects.create(code='BINDER', name='Binder', station=cls.bind_st)
        dtf = MachineType.objects.create(code='DTF', name='DTF printer', station=cls.print_st)
        Machine.objects.create(branch=cls.branch, machine_type=press, name='Canon')
        Machine.objects.create(branch=cls.branch, machine_type=laminator, name='Laminator')
        Machine.objects.create(branch=cls.branch, machine_type=binder, name='Binder')
        # No DTF printer at the branch.

        def service(code, name, unit, price, station, machine_type, online=False):
            s = Service.objects.create(
                code=code, name=name, category='INSTANT', unit=unit,
                is_active=True, online=online, requires_file_upload=False,
            )
            if price is not None:
                PricingRule.objects.create(service=s, branch=None, base_price=Decimal(price), is_active=True)
            ServiceStation.objects.create(
                service=s, station=station, machine_type=machine_type, sequence=1,
                setup_minutes=Decimal('1'), minutes_per_unit=Decimal('0.5'),
            )
            return s

        cls.prints = service('T-A4COL', 'Test A4 Colour', 'sheet', '2.50', cls.print_st, press, online=True)
        cls.lam    = service('T-LAM', 'Test Lamination', 'sheet', '10.00', cls.lam_st, laminator)
        cls.bind   = service('T-BIND', 'Test Binding', 'PER_PIECE', '10.00', cls.bind_st, binder)
        cls.env    = service('T-ENV', 'Test Envelope', 'PER_PIECE', '2.00', cls.fin_st, None)
        cls.bag    = service('T-BAG', 'Test Clear Bag', 'PER_PIECE', None, cls.fin_st, None)
        cls.shirt  = service('T-DTF', 'Test DTF Shirt', 'PER_PIECE', '50.00', cls.print_st, dtf, online=True)
        cls.prints.addons.set([cls.lam, cls.bind, cls.env, cls.bag])

    # ── Availability ─────────────────────────────────────────────

    def test_available_needs_a_price_and_its_machines(self):
        self.assertTrue(can_make(self.prints, self.branch))
        self.assertFalse(can_make(self.bag))                # no price yet
        self.assertFalse(can_make(self.shirt, self.branch)) # no DTF printer
        self.assertTrue(can_make(self.env))                 # by hand needs no machine

    def test_the_catalogue_shows_online_services_and_says_what_is_coming(self):
        data = APIClient().get('/api/v1/storefront/catalogue/').json()
        by_code = {s['code']: s for s in data}

        self.assertIn('T-A4COL', by_code)
        self.assertIn('T-DTF', by_code)
        self.assertNotIn('T-LAM', by_code)        # an add-on, not sold online alone
        self.assertTrue(by_code['T-A4COL']['available'])
        self.assertFalse(by_code['T-DTF']['available'])

        addons = {a['name']: a for a in by_code['T-A4COL']['addons']}
        self.assertTrue(addons['Test Lamination']['available'])
        self.assertFalse(addons['Test Clear Bag']['available'])

    # ── Pricing add-ons ──────────────────────────────────────────

    def test_lamination_counts_sheets_and_binding_counts_copies(self):
        self._ring_tiers()
        priced, total, problem = price_addons(
            self.prints, [self.lam.pk, self.bind.pk], quantity=3, specs={'pages': 4},
        )
        self.assertIsNone(problem)
        by_name = {a['service_name']: a for a in priced}
        self.assertEqual(by_name['Test Lamination']['quantity'], 12)   # 3 copies × 4 pages
        self.assertEqual(by_name['Test Binding']['quantity'], 3)       # 3 copies
        self.assertEqual(total, Decimal(by_name['Test Lamination']['total']) + Decimal(by_name['Test Binding']['total']))

    def test_an_addon_must_be_offered_and_available(self):
        _, _, not_offered = price_addons(self.prints, [self.shirt.pk], 1, {})
        _, _, unavailable = price_addons(self.prints, [self.bag.pk], 1, {})
        self.assertIsNotNone(not_offered)
        self.assertIn('not available', unavailable)

    def test_the_quote_includes_the_addons(self):
        main = Decimal(str(quote_line(service=self.prints, branch=None,
                                      specifications={'pages': 1}, quantity=2)['total']))
        lam = Decimal(str(quote_line(service=self.lam, branch=None,
                                     specifications={}, quantity=2)['total']))

        response = APIClient().post('/api/v1/storefront/quote/', {
            'service': self.prints.pk, 'quantity': 2,
            'specifications': {'pages': 1}, 'addons': [self.lam.pk],
        }, format='json')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Decimal(response.json()['total']), main + lam)
        self.assertEqual(len(response.json()['addons']), 1)

    def test_a_service_that_is_coming_soon_cannot_be_quoted(self):
        response = APIClient().post('/api/v1/storefront/quote/', {
            'service': self.shirt.pk, 'quantity': 1, 'specifications': {},
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_an_envelope_is_per_copy_whatever_the_pages(self):
        # 3 copies of a 6-sheet document: 3 envelopes, not 18.
        priced, total, _ = price_addons(self.prints, [self.env.pk], quantity=3, specs={'pages': 6})
        self.assertEqual(priced[0]['quantity'], 3)
        self.assertEqual(total, Decimal('6.00'))

    def test_lamination_is_every_sheet_of_every_copy(self):
        priced, total, _ = price_addons(self.prints, [self.lam.pk], quantity=3, specs={'pages': 6})
        self.assertEqual(priced[0]['quantity'], 18)
        self.assertEqual(total, Decimal('180.00'))

    def _ring_tiers(self):
        # The live A4 binding tiers.
        PricingRule.objects.filter(service=self.bind).update(pricing_tiers=[
            {'min': 8, 'max': 20, 'condition': 'ring_size', 'flat_price': 10.0},
            {'min': 22, 'max': 30, 'condition': 'ring_size', 'flat_price': 15.0},
            {'min': 32, 'max': None, 'condition': 'ring_size', 'flat_price': 20.0},
        ])

    def test_binding_picks_its_ring_from_the_sheets_and_charges_per_copy(self):
        self._ring_tiers()
        priced, total, _ = price_addons(self.prints, [self.bind.pk], quantity=3, specs={'pages': 6})
        self.assertEqual(priced[0]['detail'], '8mm ring')
        self.assertEqual(total, Decimal('30.00'))      # 3 copies × GHS 10

    def test_a_thicker_copy_needs_a_bigger_ring(self):
        self._ring_tiers()
        priced, total, _ = price_addons(self.prints, [self.bind.pk], quantity=3, specs={'pages': 210})
        self.assertEqual(priced[0]['detail'], '25mm ring')
        self.assertEqual(total, Decimal('45.00'))      # 3 copies × GHS 15

    def test_too_thick_to_ring_bind_is_refused(self):
        self._ring_tiers()
        _, _, problem = price_addons(self.prints, [self.bind.pk], quantity=1, specs={'pages': 600})
        self.assertIn('too thick', problem)

    # ── From the cart to the floor ───────────────────────────────

    def _converted(self):
        from apps.storefront.services.conversion import _carry_lines
        from apps.storefront.views import OrderDetailView

        priced, total, problem = OrderDetailView._price([{
            'service': self.prints.pk, 'quantity': 1,
            'specifications': {'pages': 2},
            'addons': [self.lam.pk, self.env.pk],
        }])
        self.assertIsNone(problem)

        job = Job.objects.create(
            branch=self.branch, job_type='PRODUCTION', status=Job.PAID,
            title='Add-on test', intake_by=None, estimated_cost=total,
            daily_sheet=self.sheet, intake_channel='ONLINE',
            payment_state='SETTLED', work_state='RECEIVED',
            handover_state='AWAITING_COLLECTION',
            estimated_ready_at=timezone.now() + timedelta(hours=2),
        )
        _carry_lines(SimpleNamespace(line_items=priced, order_number='ORD-TEST'), job)
        return job, priced

    def test_the_order_line_keeps_its_addons_and_their_price(self):
        _, priced = self._converted()
        line = priced[0]
        self.assertEqual(len(line['addons']), 2)
        self.assertEqual(
            Decimal(line['total']),
            Decimal(line['base_total']) + sum(Decimal(a['total']) for a in line['addons']),
        )

    def test_conversion_attaches_addons_to_their_piece(self):
        job, _ = self._converted()
        parent = job.line_items.get(parent__isnull=True)
        self.assertEqual(
            sorted(a.service.code for a in parent.addons.all()), ['T-ENV', 'T-LAM'],
        )

    def test_the_piece_is_printed_then_laminated_then_packed(self):
        job, _ = self._converted()
        build_steps(job)

        parent = job.line_items.get(parent__isnull=True)
        self.assertEqual(
            [s.station.code for s in parent.steps.order_by('sequence')],
            ['PRINT', 'LAMINATE', 'FINISH'],
        )
        self.assertFalse(JobLineItem.objects.filter(job=job, parent__isnull=False, steps__isnull=False).exists())

    def test_the_final_check_lists_the_addons(self):
        from apps.jobs.services.final_check import ordered_rows
        job, _ = self._converted()
        parent = job.line_items.get(parent__isnull=True)

        rows = {r['field']: r['ordered'] for r in ordered_rows(parent)}

        self.assertIn('Test Lamination', rows['addons'])
        self.assertIn('Test Envelope', rows['addons'])


class SidesTests(CatalogueTests):
    """One product on the storefront, with the sides chosen on it."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.prints.display_name = 'Test Colour Printing'
        cls.prints.variant_label = 'Front only'
        cls.prints.save()
        cls.both = Service.objects.create(
            code='T-A4COL2', name='Test A4 Colour 2-sided', category='INSTANT', unit='sheet',
            is_active=True, online=True, requires_file_upload=False,
            display_name='Test Colour Printing', variant_of=cls.prints,
            variant_label='Front and back',
        )
        PricingRule.objects.create(service=cls.both, branch=None, base_price=Decimal('4.00'), is_active=True)
        ServiceStation.objects.create(
            service=cls.both, station=cls.print_st,
            machine_type=MachineType.objects.get(code='DIGITAL_PRESS'), sequence=1,
            setup_minutes=Decimal('1'), minutes_per_unit=Decimal('0.5'),
        )

    def test_the_pair_is_one_product_with_a_choice_of_sides(self):
        data = APIClient().get('/api/v1/storefront/catalogue/').json()
        codes = [s['code'] for s in data]

        self.assertIn('T-A4COL', codes)
        self.assertNotIn('T-A4COL2', codes)

        product = next(s for s in data if s['code'] == 'T-A4COL')
        self.assertEqual(product['name'], 'Test Colour Printing')
        self.assertEqual(
            [(v['id'], v['label']) for v in product['variants']],
            [(self.prints.pk, 'Front only'), (self.both.pk, 'Front and back')],
        )

    def test_each_side_keeps_its_own_price(self):
        data = APIClient().get('/api/v1/storefront/catalogue/').json()
        product = next(s for s in data if s['code'] == 'T-A4COL')
        both = next(v for v in product['variants'] if v['label'] == 'Front and back')

        response = APIClient().post('/api/v1/storefront/quote/', {
            'service': both['id'], 'quantity': 1, 'specifications': {'pages': 1},
        }, format='json')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['service'], self.both.pk)


class SheetsTests(TestCase):
    """Sheets per copy come from the file's pages and the sides."""

    def _service(self, label):
        return SimpleNamespace(variant_label=label, requires_file_upload=True,
                               spec_template=[{'key': 'pages'}])

    def test_front_only_is_a_sheet_a_page(self):
        from apps.jobs.services.availability import sheets_for
        self.assertEqual(sheets_for(self._service('Front only'), 10), 10)

    def test_front_and_back_is_two_pages_a_sheet_rounded_up(self):
        from apps.jobs.services.availability import sheets_for
        self.assertEqual(sheets_for(self._service('Front and back'), 10), 5)
        self.assertEqual(sheets_for(self._service('Front and back'), 7), 4)

    def test_an_image_is_one_page(self):
        from apps.jobs.services.availability import sheets_for
        self.assertEqual(sheets_for(self._service('Front only'), None), 1)

    def test_only_file_priced_by_the_sheet_counts_pages(self):
        from apps.jobs.services.availability import counts_pages
        self.assertTrue(counts_pages(self._service('Front only')))
        self.assertFalse(counts_pages(SimpleNamespace(
            requires_file_upload=True, spec_template=[{'key': 'quantity'}])))