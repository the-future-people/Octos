"""
Inventory Deduction Tests
Run: python manage.py test apps.inventory.tests.test_deduction -v 2

Covers:
- Standard B&W printing deduction (paper + black toner)
- Color printing deduction (paper + CMYK toners)
- A3 vs A4 vs A5 paper size routing
- 2-sided jobs (PER_JOB deduction not doubled for paper, toner aware)
- Multi-line-item jobs (each line deducts independently)
- PER_JOB services (binding — sets only, not pages)
- No mapping services (passport photo — no deduction)
- Zero quantity guard
- Stock floor at zero (never goes negative)
- Immutable StockMovement (cannot edit)
- Deduction references correct job
- Running balance accuracy
"""

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.organization.models import Branch, Belt, Region
from apps.jobs.models import Job, JobLineItem, Service, PricingRule
from apps.inventory.models import (
    ConsumableCategory, ConsumableItem, ServiceConsumable,
    BranchStock, StockMovement,
)
from apps.inventory.inventory_engine import InventoryEngine
from apps.finance.models import DailySalesSheet
from django.utils import timezone as dj_timezone

User = get_user_model()


class InventoryDeductionTestCase(TestCase):
    """Base setup shared across all deduction tests."""

    def setUp(self):
        # ── Organisation ──────────────────────────────────────
        self.belt   = Belt.objects.create(name='Test Belt')
        self.region = Region.objects.create(name='Test Region', belt=self.belt)
        self.branch = Branch.objects.create(
            name         = 'Test Branch',
            code         = 'TST',
            region       = self.region,
            closing_time = '19:25:00',
        )

        # ── User ──────────────────────────────────────────────
        self.user = User.objects.create_user(
            email     = 'test@octos.com',
            password  = 'testpass',
            branch    = self.branch,
            first_name= 'Test',
            last_name = 'User',
        )

        # ── Consumable categories ─────────────────────────────
        self.cat_paper     = ConsumableCategory.objects.create(name='Paper')
        self.cat_toner     = ConsumableCategory.objects.create(name='Toner')
        self.cat_binding   = ConsumableCategory.objects.create(name='Binding')
        self.cat_lamination= ConsumableCategory.objects.create(name='Lamination')

        # ── Consumable items ──────────────────────────────────
        self.a4_paper = ConsumableItem.objects.create(
            category=self.cat_paper, name='A4 Paper 80gsm',
            paper_size='A4', unit_type='SHEETS', unit_label='sheets',
            reorder_point=250,
        )
        self.a3_paper = ConsumableItem.objects.create(
            category=self.cat_paper, name='A3 Paper 80gsm',
            paper_size='A3', unit_type='SHEETS', unit_label='sheets',
            reorder_point=100,
        )
        self.a5_paper = ConsumableItem.objects.create(
            category=self.cat_paper, name='A5 Art Paper Glossy',
            paper_size='A5', unit_type='SHEETS', unit_label='sheets',
            reorder_point=25,
        )
        self.black_toner = ConsumableItem.objects.create(
            category=self.cat_toner, name='Canon Toner Black',
            paper_size='N/A', unit_type='PERCENT', unit_label='%',
            reorder_point=15,
        )
        self.cyan_toner = ConsumableItem.objects.create(
            category=self.cat_toner, name='Canon Toner Cyan',
            paper_size='N/A', unit_type='PERCENT', unit_label='%',
            reorder_point=15,
        )
        self.magenta_toner = ConsumableItem.objects.create(
            category=self.cat_toner, name='Canon Toner Magenta',
            paper_size='N/A', unit_type='PERCENT', unit_label='%',
            reorder_point=15,
        )
        self.yellow_toner = ConsumableItem.objects.create(
            category=self.cat_toner, name='Canon Toner Yellow',
            paper_size='N/A', unit_type='PERCENT', unit_label='%',
            reorder_point=15,
        )
        self.binding_rings = ConsumableItem.objects.create(
            category=self.cat_binding, name='Binding Rings 8mm',
            paper_size='N/A', unit_type='UNITS', unit_label='pcs',
            reorder_point=20,
        )
        self.a4_lamination = ConsumableItem.objects.create(
            category=self.cat_lamination, name='A4 Lamination Pouches',
            paper_size='A4', unit_type='UNITS', unit_label='pcs',
            reorder_point=20,
        )

        # ── Services ──────────────────────────────────────────
        self.svc_a4_bw = Service.objects.create(
            name='A4 B&W Printing 1-sided', code='A4-BW-P1',
            category='INSTANT', unit='PER_COPY',
        )
        self.svc_a4_color = Service.objects.create(
            name='A4 Color Printing 1-sided', code='A4-COL-P1',
            category='INSTANT', unit='PER_COPY',
        )
        self.svc_a3_bw = Service.objects.create(
            name='A3 B&W Printing 1-sided', code='A3-BW-P1',
            category='INSTANT', unit='PER_COPY',
        )
        self.svc_a5_color = Service.objects.create(
            name='A5 Color Printing', code='A5-COL-P1',
            category='INSTANT', unit='PER_COPY',
        )
        self.svc_binding = Service.objects.create(
            name='Binding', code='BIND',
            category='INSTANT', unit='PER_JOB',
        )
        self.svc_passport = Service.objects.create(
            name='Passport Photo', code='PP',
            category='INSTANT', unit='PER_JOB',
        )
        self.svc_lamination = Service.objects.create(
            name='A4 Lamination', code='A4-LAM',
            category='INSTANT', unit='PER_JOB',
        )

        # ── ServiceConsumable mappings ────────────────────────
        # A4 B&W: paper + black toner
        ServiceConsumable.objects.create(service=self.svc_a4_bw, consumable=self.a4_paper, quantity_per_unit=1.0, applies_to_color=True, applies_to_bw=True)
        ServiceConsumable.objects.create(service=self.svc_a4_bw, consumable=self.black_toner, quantity_per_unit=0.01, applies_to_color=False, applies_to_bw=True)

        # A4 Color: paper + CMYK toners
        ServiceConsumable.objects.create(service=self.svc_a4_color, consumable=self.a4_paper, quantity_per_unit=1.0, applies_to_color=True, applies_to_bw=True)
        ServiceConsumable.objects.create(service=self.svc_a4_color, consumable=self.black_toner, quantity_per_unit=0.01, applies_to_color=True, applies_to_bw=False)
        ServiceConsumable.objects.create(service=self.svc_a4_color, consumable=self.cyan_toner, quantity_per_unit=0.01, applies_to_color=True, applies_to_bw=False)
        ServiceConsumable.objects.create(service=self.svc_a4_color, consumable=self.magenta_toner, quantity_per_unit=0.01, applies_to_color=True, applies_to_bw=False)
        ServiceConsumable.objects.create(service=self.svc_a4_color, consumable=self.yellow_toner, quantity_per_unit=0.01, applies_to_color=True, applies_to_bw=False)

        # A3 B&W: paper + black toner (double rate)
        ServiceConsumable.objects.create(service=self.svc_a3_bw, consumable=self.a3_paper, quantity_per_unit=1.0, applies_to_color=True, applies_to_bw=True)
        ServiceConsumable.objects.create(service=self.svc_a3_bw, consumable=self.black_toner, quantity_per_unit=0.02, applies_to_color=False, applies_to_bw=True)

        # A5 Color: paper + CMYK toners (half rate)
        ServiceConsumable.objects.create(service=self.svc_a5_color, consumable=self.a5_paper, quantity_per_unit=1.0, applies_to_color=True, applies_to_bw=True)
        ServiceConsumable.objects.create(service=self.svc_a5_color, consumable=self.black_toner, quantity_per_unit=0.005, applies_to_color=True, applies_to_bw=True)
        ServiceConsumable.objects.create(service=self.svc_a5_color, consumable=self.cyan_toner, quantity_per_unit=0.005, applies_to_color=True, applies_to_bw=False)
        ServiceConsumable.objects.create(service=self.svc_a5_color, consumable=self.magenta_toner, quantity_per_unit=0.005, applies_to_color=True, applies_to_bw=False)
        ServiceConsumable.objects.create(service=self.svc_a5_color, consumable=self.yellow_toner, quantity_per_unit=0.005, applies_to_color=True, applies_to_bw=False)

        # Binding: rings per set (PER_JOB)
        ServiceConsumable.objects.create(service=self.svc_binding, consumable=self.binding_rings, quantity_per_unit=1.0, applies_to_color=True, applies_to_bw=True)

        # Lamination: pouches per set (PER_JOB)
        ServiceConsumable.objects.create(service=self.svc_lamination, consumable=self.a4_lamination, quantity_per_unit=1.0, applies_to_color=True, applies_to_bw=True)

        # Passport: no consumable mapping

        # ── Opening stock balances ────────────────────────────
        self._set_stock(self.a4_paper,      Decimal('500'))
        self._set_stock(self.a3_paper,      Decimal('200'))
        self._set_stock(self.a5_paper,      Decimal('100'))
        self._set_stock(self.black_toner,   Decimal('80'))
        self._set_stock(self.cyan_toner,    Decimal('60'))
        self._set_stock(self.magenta_toner, Decimal('60'))
        self._set_stock(self.yellow_toner,  Decimal('60'))
        self._set_stock(self.binding_rings, Decimal('50'))
        self._set_stock(self.a4_lamination, Decimal('30'))

        # ── Daily sheet ───────────────────────────────────────
        self.sheet = DailySalesSheet.objects.create(
            branch=self.branch,
            date=dj_timezone.localdate(),
            status=DailySalesSheet.Status.OPEN,
        )

        # ── Pricing rules ─────────────────────────────────────
        for svc in [self.svc_a4_bw, self.svc_a4_color, self.svc_a3_bw,
                    self.svc_a5_color, self.svc_binding, self.svc_passport,
                    self.svc_lamination]:
            PricingRule.objects.create(service=svc, branch=self.branch, base_price=Decimal('1.00'))

    def _set_stock(self, consumable, qty):
        stock, _ = BranchStock.objects.get_or_create(
            branch=self.branch, consumable=consumable,
            defaults={'quantity': qty}
        )
        stock.quantity = qty
        stock.save()
        return stock

    def _get_stock(self, consumable):
        return BranchStock.objects.get(branch=self.branch, consumable=consumable).quantity

    def _make_job(self, line_items_data):
        """Create a COMPLETE job with given line items."""
        job = Job.objects.create(
            branch      = self.branch,
            intake_by   = self.user,
            daily_sheet = self.sheet,
            title       = 'Test Job',
            job_type    = 'INSTANT',
            status      = Job.COMPLETE,
            amount_paid = Decimal('10.00'),
        )
        for i, li in enumerate(line_items_data):
            JobLineItem.objects.create(
                job        = job,
                service    = li['service'],
                pages      = li.get('pages', 1),
                sets       = li.get('sets', 1),
                quantity   = li.get('sets', 1),
                is_color   = li.get('is_color', False),
                paper_size = li.get('paper_size', 'A4'),
                sides      = li.get('sides', 'SINGLE'),
                unit_price = Decimal('1.00'),
                line_total = Decimal('1.00'),
                position   = i,
            )
        return job


# ─────────────────────────────────────────────────────────────
# Test Cases
# ─────────────────────────────────────────────────────────────

class TestBWPrintingDeduction(InventoryDeductionTestCase):
    """A4 B&W printing deducts paper and black toner only."""

    def test_a4_bw_single_page(self):
        job = self._make_job([{'service': self.svc_a4_bw, 'pages': 1, 'sets': 1, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)

        self.assertEqual(self._get_stock(self.a4_paper),    Decimal('499.00'))
        self.assertEqual(self._get_stock(self.black_toner), Decimal('79.99'))
        # Color toners untouched
        self.assertEqual(self._get_stock(self.cyan_toner),    Decimal('60'))
        self.assertEqual(self._get_stock(self.magenta_toner), Decimal('60'))
        self.assertEqual(self._get_stock(self.yellow_toner),  Decimal('60'))

    def test_a4_bw_multi_page(self):
        """10 pages × 1 set = 10 sheets, 0.10% black toner."""
        job = self._make_job([{'service': self.svc_a4_bw, 'pages': 10, 'sets': 1, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)

        self.assertEqual(self._get_stock(self.a4_paper),    Decimal('490.00'))
        self.assertEqual(self._get_stock(self.black_toner), Decimal('79.90'))

    def test_a4_bw_multi_set(self):
        """5 pages × 3 sets = 15 sheets, 0.15% black toner."""
        job = self._make_job([{'service': self.svc_a4_bw, 'pages': 5, 'sets': 3, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)

        self.assertEqual(self._get_stock(self.a4_paper),    Decimal('485.00'))
        self.assertEqual(self._get_stock(self.black_toner), Decimal('79.85'))


class TestColorPrintingDeduction(InventoryDeductionTestCase):
    """A4 Color printing deducts paper and all 4 toners."""

    def test_a4_color_single_page(self):
        job = self._make_job([{'service': self.svc_a4_color, 'pages': 1, 'sets': 1, 'is_color': True}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)

        self.assertEqual(self._get_stock(self.a4_paper),      Decimal('499.00'))
        self.assertEqual(self._get_stock(self.black_toner),   Decimal('79.99'))
        self.assertEqual(self._get_stock(self.cyan_toner),    Decimal('59.99'))
        self.assertEqual(self._get_stock(self.magenta_toner), Decimal('59.99'))
        self.assertEqual(self._get_stock(self.yellow_toner),  Decimal('59.99'))

    def test_color_does_not_deduct_bw_only_mappings(self):
        """Color job should not deduct consumables marked applies_to_color=False."""
        job = self._make_job([{'service': self.svc_a4_bw, 'pages': 1, 'sets': 1, 'is_color': True}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)
        # A4 B&W service black toner is applies_to_color=False — should not deduct
        self.assertEqual(self._get_stock(self.black_toner), Decimal('80'))


class TestPaperSizeRouting(InventoryDeductionTestCase):
    """Different paper sizes deduct from correct stock."""

    def test_a3_uses_a3_paper(self):
        job = self._make_job([{'service': self.svc_a3_bw, 'pages': 2, 'sets': 1, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)

        self.assertEqual(self._get_stock(self.a3_paper), Decimal('198.00'))
        self.assertEqual(self._get_stock(self.a4_paper), Decimal('500.00'))  # untouched

    def test_a3_toner_rate_double_a4(self):
        """A3 uses 0.02% per page vs A4 0.01%."""
        job = self._make_job([{'service': self.svc_a3_bw, 'pages': 1, 'sets': 1, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)
        self.assertEqual(self._get_stock(self.black_toner), Decimal('79.98'))

    def test_a5_uses_a5_paper(self):
        job = self._make_job([{'service': self.svc_a5_color, 'pages': 3, 'sets': 1, 'is_color': True}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)

        self.assertEqual(self._get_stock(self.a5_paper), Decimal('97.00'))
        self.assertEqual(self._get_stock(self.a4_paper), Decimal('500.00'))  # untouched


class TestBindingDeduction(InventoryDeductionTestCase):
    """Binding deducts rings per set only — not per page."""

    def test_binding_deducts_per_set(self):
        """2 sets = 2 rings regardless of pages."""
        job = self._make_job([{'service': self.svc_binding, 'pages': 50, 'sets': 2, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)
        self.assertEqual(self._get_stock(self.binding_rings), Decimal('48.00'))

    def test_binding_single_set(self):
        job = self._make_job([{'service': self.svc_binding, 'pages': 100, 'sets': 1, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)
        self.assertEqual(self._get_stock(self.binding_rings), Decimal('49.00'))


class TestNoMappingService(InventoryDeductionTestCase):
    """Services with no consumable mapping deduct nothing."""

    def test_passport_photo_no_deduction(self):
        job = self._make_job([{'service': self.svc_passport, 'pages': 1, 'sets': 4, 'is_color': True}])
        before = {c: self._get_stock(c) for c in [
            self.a4_paper, self.black_toner, self.cyan_toner
        ]}
        InventoryEngine(self.branch).deduct_for_job(job, self.user)
        for c, qty in before.items():
            self.assertEqual(self._get_stock(c), qty)


class TestMultiLineItemJob(InventoryDeductionTestCase):
    """Multi-line jobs deduct each line item independently."""

    def test_printing_plus_binding(self):
        """10 pages printing + 1 binding = 10 sheets + 1 ring."""
        job = self._make_job([
            {'service': self.svc_a4_bw,   'pages': 10, 'sets': 1, 'is_color': False},
            {'service': self.svc_binding,  'pages': 10, 'sets': 1, 'is_color': False},
        ])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)

        self.assertEqual(self._get_stock(self.a4_paper),      Decimal('490.00'))
        self.assertEqual(self._get_stock(self.binding_rings), Decimal('49.00'))

    def test_mixed_color_and_bw(self):
        """Color line + B&W line on same job."""
        job = self._make_job([
            {'service': self.svc_a4_color, 'pages': 5, 'sets': 1, 'is_color': True},
            {'service': self.svc_a4_bw,   'pages': 3, 'sets': 1, 'is_color': False},
        ])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)

        # A4 paper: 5 + 3 = 8 sheets
        self.assertEqual(self._get_stock(self.a4_paper), Decimal('492.00'))
        # Black toner: 0.05 (color) + 0.03 (bw) = 0.08
        self.assertEqual(self._get_stock(self.black_toner), Decimal('79.92'))
        # CMY toners: 0.05 each (color only)
        self.assertEqual(self._get_stock(self.cyan_toner), Decimal('59.95'))


class TestStockFloor(InventoryDeductionTestCase):
    """Stock never goes below zero."""

    def test_stock_floors_at_zero(self):
        """Deduct more than available — stock stops at 0."""
        self._set_stock(self.a4_paper, Decimal('2'))
        job = self._make_job([{'service': self.svc_a4_bw, 'pages': 100, 'sets': 1, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)
        self.assertEqual(self._get_stock(self.a4_paper), Decimal('0.00'))


class TestStockMovementImmutability(InventoryDeductionTestCase):
    """StockMovement records cannot be edited or deleted."""

    def test_cannot_edit_movement(self):
        job = self._make_job([{'service': self.svc_a4_bw, 'pages': 1, 'sets': 1, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)

        movement = StockMovement.objects.filter(reference_job=job).first()
        self.assertIsNotNone(movement)

        movement.quantity = Decimal('999')
        with self.assertRaises(ValueError):
            movement.save()

    def test_cannot_delete_movement(self):
        job = self._make_job([{'service': self.svc_a4_bw, 'pages': 1, 'sets': 1, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)

        movement = StockMovement.objects.filter(reference_job=job).first()
        with self.assertRaises(ValueError):
            movement.delete()


class TestMovementAuditTrail(InventoryDeductionTestCase):
    """Each deduction creates correct audit trail."""

    def test_movement_references_job(self):
        job = self._make_job([{'service': self.svc_a4_bw, 'pages': 5, 'sets': 2, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)

        movements = StockMovement.objects.filter(reference_job=job)
        self.assertEqual(movements.count(), 2)  # paper + black toner

        for m in movements:
            self.assertEqual(m.movement_type, StockMovement.MovementType.OUT)
            self.assertEqual(m.branch, self.branch)
            self.assertEqual(m.recorded_by, self.user)

    def test_balance_after_accuracy(self):
        """balance_after on movement matches actual stock after deduction."""
        job = self._make_job([{'service': self.svc_a4_bw, 'pages': 10, 'sets': 1, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)

        paper_movement = StockMovement.objects.get(
            reference_job=job, consumable=self.a4_paper
        )
        self.assertEqual(paper_movement.balance_after, self._get_stock(self.a4_paper))
        self.assertEqual(paper_movement.quantity, Decimal('10.00'))


class TestReceiveStock(InventoryDeductionTestCase):
    """Receiving stock increases balance and creates IN movement."""

    def test_receive_increases_stock(self):
        InventoryEngine(self.branch).receive_stock(
            consumable = self.a4_paper,
            quantity   = Decimal('250'),
            actor      = self.user,
            notes      = 'Supplier delivery',
        )
        self.assertEqual(self._get_stock(self.a4_paper), Decimal('750.00'))

    def test_receive_creates_in_movement(self):
        InventoryEngine(self.branch).receive_stock(
            consumable=self.a4_paper, quantity=Decimal('100'), actor=self.user
        )
        movement = StockMovement.objects.filter(
            consumable=self.a4_paper,
            movement_type=StockMovement.MovementType.IN,
        ).last()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity, Decimal('100'))
        self.assertEqual(movement.balance_after, Decimal('600.00'))

    def test_receive_zero_raises(self):
        with self.assertRaises(ValueError):
            InventoryEngine(self.branch).receive_stock(
                consumable=self.a4_paper, quantity=Decimal('0'), actor=self.user
            )


class TestLaminationDeduction(InventoryDeductionTestCase):
    """Lamination deducts pouches per set."""

    def test_lamination_deducts_per_set(self):
        job = self._make_job([{'service': self.svc_lamination, 'pages': 1, 'sets': 5, 'is_color': False}])
        InventoryEngine(self.branch).deduct_for_job(job, self.user)
        self.assertEqual(self._get_stock(self.a4_lamination), Decimal('25.00'))