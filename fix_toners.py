from apps.inventory.models import ConsumableItem, BranchStock, StockMovement, ServiceConsumable
from apps.accounts.models import CustomUser
from apps.organization.models import Branch
from decimal import Decimal

branch = Branch.objects.get(name='Westland Branch')
actor  = CustomUser.objects.filter(branch=branch, role__name='BRANCH_MANAGER').first()
print('Actor:', actor)
print('Branch:', branch)

# ── Step 1: Reset toner levels to match machine readings ──
corrections = {
    'Canon 5535i Toner Black'  : Decimal('20.00'),
    'Canon 5535i Toner Yellow' : Decimal('30.00'),
    'Canon 5535i Toner Magenta': Decimal('40.00'),
    'Canon 5535i Toner Cyan'   : Decimal('90.00'),
}

print('\nResetting toner levels:')
for name, target_pct in corrections.items():
    try:
        consumable = ConsumableItem.objects.get(name=name)
        stock, _   = BranchStock.objects.get_or_create(
            branch=branch, consumable=consumable,
            defaults={'quantity': Decimal('0')}
        )
        old = stock.quantity
        movement = StockMovement.objects.create(
            branch        = branch,
            consumable    = consumable,
            movement_type = StockMovement.MovementType.CORRECTION,
            quantity      = abs(target_pct - old),
            balance_after = target_pct,
            recorded_by   = actor,
            notes         = f'Manual correction to match machine reading ({target_pct}%)'
        )
        stock.quantity      = target_pct
        stock.last_movement = movement
        stock.save(update_fields=['quantity', 'last_movement', 'updated_at'])
        print(f'  {name}: {old}% → {target_pct}%')
    except Exception as e:
        print(f'  ERROR {name}: {e}')

# ── Step 2: Fix per-page deduction rates ──
# Black: 1/69000 * 100 = 0.00145% per page → 0.0015
# CMY:   1/60000 * 100 = 0.00167% per page → 0.0017
rate_map = {
    'Canon 5535i Toner Black'  : Decimal('0.0015'),
    'Canon 5535i Toner Cyan'   : Decimal('0.0017'),
    'Canon 5535i Toner Magenta': Decimal('0.0017'),
    'Canon 5535i Toner Yellow' : Decimal('0.0017'),
}

print('\nUpdating deduction rates:')
for name, new_rate in rate_map.items():
    updated = ServiceConsumable.objects.filter(
        consumable__name=name
    ).update(quantity_per_unit=new_rate)
    print(f'  {name}: {new_rate}% per page — {updated} mapping(s) updated')

print('\nDone.')