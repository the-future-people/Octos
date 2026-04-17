from __future__ import annotations
import logging
from decimal import Decimal
from django.db import transaction

logger = logging.getLogger(__name__)


class InventoryEngine:
    def __init__(self, branch):
        self.branch = branch

    @transaction.atomic
    def deduct_for_job(self, job, actor):
        from apps.inventory.models import ServiceConsumable, BranchStock, StockMovement
        movements = []
        line_items = job.line_items.select_related('service').all()
        for li in line_items:
            mappings = ServiceConsumable.objects.filter(service=li.service).select_related('consumable')
            for mapping in mappings:
                consumable = mapping.consumable
                if li.is_color and not mapping.applies_to_color:
                    continue
                if not li.is_color and not mapping.applies_to_bw:
                    continue
                pages    = li.pages or 1
                sets     = li.sets  or 1
                # For PER_JOB services (binding, lamination etc),
                # deduct per set only — not per page
                from apps.jobs.models import Service
                if li.service.unit in ('PER_JOB', 'PER_PIECE'):
                    quantity = Decimal(str(mapping.quantity_per_unit)) * sets
                else:
                    quantity = Decimal(str(mapping.quantity_per_unit)) * pages * sets
                quantity = quantity.quantize(Decimal('0.01'))
                if quantity <= 0:
                    continue
                stock, _ = BranchStock.objects.get_or_create(branch=self.branch, consumable=consumable, defaults={'quantity': Decimal('0')})
                new_balance = max(Decimal('0'), stock.quantity - quantity)
                movement = StockMovement.objects.create(branch=self.branch, consumable=consumable, movement_type=StockMovement.MovementType.OUT, quantity=quantity, balance_after=new_balance, reference_job=job, recorded_by=actor, notes=f"Auto-deducted for job {job.job_number}")
                stock.quantity = new_balance
                stock.last_movement = movement
                stock.save(update_fields=['quantity', 'last_movement', 'updated_at'])
                movements.append(movement)
                self._check_reorder_alert(stock, actor)
        return movements

    @transaction.atomic
    def receive_stock(self, consumable, quantity, actor, notes=''):
        from apps.inventory.models import BranchStock, StockMovement
        quantity = Decimal(str(quantity)).quantize(Decimal('0.01'))
        if quantity <= 0:
            raise ValueError('Quantity must be positive.')
        stock, _ = BranchStock.objects.get_or_create(branch=self.branch, consumable=consumable, defaults={'quantity': Decimal('0')})
        new_balance = stock.quantity + quantity
        movement = StockMovement.objects.create(branch=self.branch, consumable=consumable, movement_type=StockMovement.MovementType.IN, quantity=quantity, balance_after=new_balance, recorded_by=actor, notes=notes or f"Stock received")
        stock.quantity = new_balance
        stock.last_movement = movement
        stock.save(update_fields=['quantity', 'last_movement', 'updated_at'])
        return movement

    @transaction.atomic
    def set_opening_balance(self, consumable, quantity, actor, notes=''):
        from apps.inventory.models import BranchStock, StockMovement
        quantity = Decimal(str(quantity)).quantize(Decimal('0.01'))
        stock, _ = BranchStock.objects.get_or_create(branch=self.branch, consumable=consumable, defaults={'quantity': Decimal('0')})
        movement = StockMovement.objects.create(branch=self.branch, consumable=consumable, movement_type=StockMovement.MovementType.OPENING, quantity=quantity, balance_after=quantity, recorded_by=actor, notes=notes or 'Opening balance')
        stock.quantity = quantity
        stock.last_movement = movement
        stock.save(update_fields=['quantity', 'last_movement', 'updated_at'])
        return movement

    @transaction.atomic
    def record_waste(self, consumable, quantity, reason, actor, job=None, notes=''):
        from apps.inventory.models import BranchStock, StockMovement, WasteIncident
        quantity = Decimal(str(quantity)).quantize(Decimal('0.01'))
        if quantity <= 0:
            raise ValueError('Waste quantity must be positive.')
        stock, _ = BranchStock.objects.get_or_create(branch=self.branch, consumable=consumable, defaults={'quantity': Decimal('0')})
        new_balance = max(Decimal('0'), stock.quantity - quantity)
        movement = StockMovement.objects.create(branch=self.branch, consumable=consumable, movement_type=StockMovement.MovementType.WASTE, quantity=quantity, balance_after=new_balance, reference_job=job, recorded_by=actor, notes=notes or f"Waste: {reason}")
        stock.quantity = new_balance
        stock.last_movement = movement
        stock.save(update_fields=['quantity', 'last_movement', 'updated_at'])
        incident = WasteIncident.objects.create(branch=self.branch, consumable=consumable, quantity=quantity, reason=reason, job=job, reported_by=actor, notes=notes, stock_movement=movement)
        self._check_reorder_alert(stock, actor)
        return incident
    
    def generate_daily_snapshot(self, date):
        from apps.inventory.models import BranchStock, StockMovement
        snapshot = {
            'date'     : date.isoformat(),
            'branch'   : self.branch.code,
            'items'    : [],
            'low_stock': [],
        }
        stocks = BranchStock.objects.filter(
            branch=self.branch
        ).select_related('consumable', 'consumable__category')

        for stock in stocks:
            day_movements = StockMovement.objects.filter(
                branch       = self.branch,
                consumable   = stock.consumable,
                created_at__date = date,
            )
            consumed = sum(
                float(m.quantity) for m in day_movements
                if m.movement_type in ['OUT', 'WASTE']
            )
            received = sum(
                float(m.quantity) for m in day_movements
                if m.movement_type == 'IN'
            )

            # Skip consumables with zero activity today
            if consumed == 0 and received == 0:
                continue

            closing = float(stock.quantity)
            opening = closing - received + consumed

            snapshot['items'].append({
                'consumable'   : str(stock.consumable),
                'category'     : stock.consumable.category.name,
                'unit'         : stock.consumable.unit_label,
                'opening'      : round(opening,  2),
                'received'     : round(received, 2),
                'consumed'     : round(consumed, 2),
                'closing'      : round(closing,  2),
                'is_low'       : stock.is_low,
                'reorder_point': float(stock.consumable.reorder_point),
            })
            if stock.is_low:
                snapshot['low_stock'].append(str(stock.consumable))

        # Sort by category then name
        snapshot['items'].sort(key=lambda x: (x['category'], x['consumable']))
        return snapshot

    def generate_weekly_snapshot(self, date_from, date_to):
        from apps.inventory.models import BranchStock, StockMovement
        snapshot = {'period': f"{date_from.isoformat()} to {date_to.isoformat()}", 'branch': self.branch.code, 'items': [], 'low_stock': []}
        stocks = BranchStock.objects.filter(branch=self.branch).select_related('consumable', 'consumable__category')
        for stock in stocks:
            period_movements = StockMovement.objects.filter(branch=self.branch, consumable=stock.consumable, created_at__date__range=[date_from, date_to])
            consumed = sum(float(m.quantity) for m in period_movements if m.movement_type in ['OUT', 'WASTE'])
            received = sum(float(m.quantity) for m in period_movements if m.movement_type == 'IN')
            opening  = float(stock.quantity) - received + consumed
            snapshot['items'].append({'consumable': str(stock.consumable), 'category': stock.consumable.category.name, 'unit': stock.consumable.unit_label, 'opening': round(opening, 2), 'received': round(received, 2), 'consumed': round(consumed, 2), 'closing': round(float(stock.quantity), 2), 'is_low': stock.is_low, 'reorder_point': stock.consumable.reorder_point})
            if stock.is_low:
                snapshot['low_stock'].append(str(stock.consumable))
        return snapshot

    def _check_reorder_alert(self, stock, actor):
        try:
            if not stock.is_low or stock.consumable.reorder_point == 0:
                return
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser
            bm = CustomUser.objects.filter(branch=self.branch).first()
            if not bm:
                return
            notify(recipient=bm, verb='stock_low', message=f"{stock.consumable.name} is low at {self.branch.name} - {float(stock.quantity):.0f} {stock.consumable.unit_label} remaining.", actor=actor)
        except Exception:
            pass

    @classmethod
    def for_branch(cls, branch):
        return cls(branch)
