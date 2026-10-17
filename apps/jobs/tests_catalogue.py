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

    def setUp(self):
        # The engine keeps price rules in the cache, and a test's
        # rollback restores the database but not the cache. Each test
        # starts clean, so one test's prices never leak into the next.
        from django.core.cache import cache
        cache.clear()

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

    def test_the_customer_says_how_copies_are_packed(self):
        envelope = Service.objects.create(
            code='ENV-PACK-A4', name='Brown Envelope (packed)', category='INSTANT',
            unit='PER_PIECE', is_active=True,
        )
        PricingRule.objects.create(service=envelope, branch=None, base_price=Decimal('2.00'), is_active=True)
        ServiceStation.objects.create(
            service=envelope, station=self.fin_st, machine_type=None, sequence=1,
            setup_minutes=Decimal('0'), minutes_per_unit=Decimal('0.5'),
        )
        self.prints.addons.add(envelope)

        def envelopes(copies, sheets, per_copy=None):
            chosen = [envelope.pk] if per_copy is None else [{'service': envelope.pk, 'per_copy': per_copy}]
            priced, _, problem = price_addons(self.prints, chosen, quantity=copies, specs={'pages': sheets})
            self.assertIsNone(problem)
            return priced[0]['quantity']

        # Octos's suggestion: a one-sheet notice travels as one bundle,
        # a six-sheet report is one envelope a set.
        self.assertEqual(envelopes(10, 1), 1)
        self.assertEqual(envelopes(3, 6), 3)
        # The customer's word wins: five letters to five employers...
        self.assertEqual(envelopes(5, 1, per_copy=True), 5)
        # ...or three reports bundled for one office.
        self.assertEqual(envelopes(3, 6, per_copy=False), 1)

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

    def test_a_price_change_applies_at_once(self):
        # Quote once, so the engine has the old rule cached.
        quote_line(service=self.lam, branch=None, specifications={}, quantity=1)

        rule = PricingRule.objects.get(service=self.lam)
        rule.base_price = Decimal('12.00')
        rule.save()

        after = quote_line(service=self.lam, branch=None, specifications={}, quantity=1)
        self.assertEqual(Decimal(str(after['total'])), Decimal('12.00'))

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

class LineMinimumTests(JobsFixtureMixin, TestCase):
    """
    Flexy and SAV: at least GHS 30 an order line, not a piece. Quantity
    counts towards it, and the minimum says how many pieces it covers.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.flexy = Service.objects.create(
            code='T-FLEXY', name='Test Flexy', category='PRODUCTION',
            unit='PER_SQFT', is_active=True,
        )
        PricingRule.objects.create(
            service=cls.flexy, branch=None, base_price=Decimal('3.25'),
            minimum_price=Decimal('30.00'), is_active=True,
        )
        cls.cut = Service.objects.create(
            code='T-SAVCUT', name='Test Cut to shape', category='PRODUCTION',
            unit='PER_SQFT', is_active=True,
        )
        PricingRule.objects.create(service=cls.cut, branch=None, base_price=Decimal('3.00'), is_active=True)
        cls.eyelets = Service.objects.create(
            code='T-EYELETS', name='Test Eyelets', category='PRODUCTION',
            unit='PER_PIECE', is_active=True,
        )
        PricingRule.objects.create(service=cls.eyelets, branch=None, base_price=Decimal('0.00'), is_active=True)
        cls.flexy.addons.set([cls.cut, cls.eyelets])

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _quote(self, w, h, quantity):
        return quote_line(service=self.flexy, branch=None,
                          specifications={'width_in': w, 'height_in': h}, quantity=quantity)

    def test_one_small_piece_pays_the_line_minimum(self):
        q = self._quote(4, 4, 1)
        self.assertEqual(Decimal(str(q['total'])), Decimal('30.00'))
        self.assertTrue(q['minimum_applied'])

    def test_three_small_pieces_are_one_minimum_not_three(self):
        self.assertEqual(Decimal(str(self._quote(4, 4, 3)['total'])), Decimal('30.00'))

    def test_the_minimum_says_how_many_pieces_it_covers(self):
        # 4x4in is 0.111 sq ft at 3.25: 0.36 a piece, so 30 covers 83.
        self.assertEqual(self._quote(4, 4, 1)['covers_up_to'], 83)

    def test_enough_pieces_climb_past_the_minimum(self):
        # 24x12in is 2 sq ft: 6.50 a piece. Two are 13 (minimum 30); ten are 65.
        self.assertEqual(Decimal(str(self._quote(24, 12, 2)['total'])), Decimal('30.00'))
        ten = self._quote(24, 12, 10)
        self.assertEqual(Decimal(str(ten['total'])), Decimal('65.00'))
        self.assertFalse(ten['minimum_applied'])

    def test_a_large_piece_is_priced_by_area(self):
        q = self._quote(72, 36, 1)
        self.assertEqual(Decimal(str(q['total'])), Decimal('58.50'))
        self.assertIsNone(q['covers_up_to'])

    def test_cutting_to_shape_is_priced_by_the_piece_area(self):
        # 12x12in is 1 sq ft; two pieces cut at 3.00 a sq ft.
        priced, total, problem = price_addons(
            self.flexy, [self.cut.pk], quantity=2, specs={'width_in': 12, 'height_in': 12},
        )
        self.assertIsNone(problem)
        self.assertEqual(total, Decimal('6.00'))

    def test_eyelets_are_free_and_offered(self):
        priced, total, problem = price_addons(
            self.flexy, [self.eyelets.pk], quantity=3, specs={'width_in': 72, 'height_in': 36},
        )
        self.assertIsNone(problem)
        self.assertEqual(total, Decimal('0.00'))
        self.assertTrue(can_make(self.eyelets))



class CheckoutRepriceTests(JobsFixtureMixin, TestCase):
    """
    Changing an order at checkout: only quantity and add-ons. What the
    server worked out (the page count from the file) stays the server's.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.prints = Service.objects.create(
            code='T-CHK', name='Test Checkout Print', category='INSTANT',
            unit='sheet', is_active=True, online=True,
        )
        PricingRule.objects.create(service=cls.prints, branch=None,
                                   base_price=Decimal('2.50'), is_active=True)

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _order(self):
        from apps.storefront.models import OnlineOrder
        from apps.storefront.views import OrderDetailView
        order = OnlineOrder.objects.create()
        priced, total, problem = OrderDetailView._price([{
            'service': self.prints.pk, 'quantity': 2,
            'specifications': {'pages': 10},
        }])
        self.assertIsNone(problem)
        order.line_items, order.total = priced, total
        order.save()
        return order

    def _patch(self, order, lines):
        return APIClient().patch(
            f'/api/v1/storefront/orders/{order.order_number}/',
            {'token': order.access_token, 'line_items': lines}, format='json',
        )

    def test_the_page_count_stays_the_servers(self):
        order = self._order()
        line = order.line_items[0]

        # A browser claiming the 10-page document is now 1 page.
        response = self._patch(order, [{
            'id': line['id'], 'service': self.prints.pk, 'quantity': 3,
            'specifications': {'pages': 1},
        }])

        self.assertEqual(response.status_code, 200, response.content)
        kept = response.json()['line_items'][0]
        self.assertEqual(kept['specifications']['pages'], 10)
        self.assertEqual(kept['quantity'], 3)
        self.assertEqual(Decimal(kept['total']), Decimal('75.00'))   # 3 x 10 x 2.50

    def test_a_line_the_order_never_had_is_refused(self):
        order = self._order()
        response = self._patch(order, [{
            'id': 'made-up', 'service': self.prints.pk, 'quantity': 1,
            'specifications': {'pages': 1},
        }])
        self.assertEqual(response.status_code, 400)

    def test_a_document_cannot_be_added_with_a_page_count_from_the_browser(self):
        self.prints.requires_file_upload = True
        self.prints.spec_template = [{'key': 'pages', 'type': 'number'}]
        self.prints.save()
        order = self._order()

        # Removing the 10-page line and adding "the same" document as 1 page.
        response = self._patch(order, [{
            'service': self.prints.pk, 'quantity': 3, 'specifications': {'pages': 1},
        }])

        self.assertEqual(response.status_code, 400)
        self.assertIn('count their pages', response.json()['detail'])

    def test_removing_a_line_still_works(self):
        order = self._order()
        response = self._patch(order, [])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['line_items'], [])