"""
Seed DeliveryUnit records for all active consumables.
Run via:
  Get-Content seed_delivery_units.py | python manage.py shell
"""
from decimal import Decimal
from apps.inventory.models import ConsumableItem
from apps.inventory.models.delivery_unit import DeliveryUnit

DELIVERY_UNITS = [
    # ── Paper ──────────────────────────────────────────────────────────
    ('A4 Paper 80gsm',          Decimal('2500'), 'box',        '1 box = 2,500 sheets (5 reams)'),
    ('A3 Paper 80gsm',          Decimal('2500'), 'box',        '1 box = 2,500 sheets (5 reams)'),
    ('A4 Art Paper Glossy',     Decimal('500'),  'ream',       '1 ream = 500 sheets'),
    ('A3 Art Paper Glossy',     Decimal('500'),  'ream',       '1 ream = 500 sheets'),
    ('A5 Art Paper Glossy',     Decimal('500'),  'ream',       '1 ream = 500 sheets'),
    ('A4 Certificate Paper',    Decimal('500'),  'ream',       '1 ream = 500 sheets'),
    ('A4 Shiny Card',           Decimal('250'),  'pack',       '1 pack = 250 pcs'),

    # ── Binding ────────────────────────────────────────────────────────
    ('A4 Binding Cover',        Decimal('100'),  'box',        '1 box = 100 sheets'),
    ('A3 Binding Cover',        Decimal('100'),  'box',        '1 box = 100 sheets'),
    ('A4 Binding Film',         Decimal('100'),  'box',        '1 box = 100 sheets'),
    ('A3 Binding Film',         Decimal('100'),  'box',        '1 box = 100 sheets'),
    ('Binding Rings 6mm',       Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 8mm',       Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 10mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 12mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 14mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 16mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 18mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 20mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 22mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 24mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 26mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 28mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 30mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 32mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 34mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('Binding Rings 36mm',      Decimal('100'),  'box',        '1 box = 100 pcs'),

    # ── Lamination ─────────────────────────────────────────────────────
    ('A4 Lamination Pouches',   Decimal('100'),  'box',        '1 box = 100 pcs'),
    ('A3 Lamination Pouches',   Decimal('100'),  'box',        '1 box = 100 pcs'),

    # ── Envelopes ──────────────────────────────────────────────────────
    ('A4 Brown Envelope',       Decimal('50'),   'pack',       '1 pack = 50 pcs'),

    # ── Toner ──────────────────────────────────────────────────────────
    ('Canon 5535i Toner Black', Decimal('1'),    'cartridge',  '1 cartridge replaces 0-100%'),
    ('Canon 5535i Toner Cyan',  Decimal('1'),    'cartridge',  '1 cartridge replaces 0-100%'),
    ('Canon 5535i Toner Magenta',Decimal('1'),   'cartridge',  '1 cartridge replaces 0-100%'),
    ('Canon 5535i Toner Yellow', Decimal('1'),   'cartridge',  '1 cartridge replaces 0-100%'),

    # ── Photography ────────────────────────────────────────────────────
    ('Passport Photo Film',     Decimal('108'),  'box',        '1 box = 6 packs × 18 film cards + 3 ink cassettes'),
]

created = 0
skipped = 0
missing = 0

for name, pack_size, pack_label, notes in DELIVERY_UNITS:
    # Match by name prefix to handle names like 'A4 Paper 80gsm (A4)'
    consumable = ConsumableItem.objects.filter(name__icontains=name, is_active=True).first()
    if consumable is None:
        print(f'  ✗ NOT FOUND: {name}')
        missing += 1
        continue

    du, was_created = DeliveryUnit.objects.get_or_create(
        consumable = consumable,
        defaults   = {
            'pack_size':  pack_size,
            'pack_label': pack_label,
            'notes':      notes,
        },
    )
    if was_created:
        print(f'  ✓ Created: {consumable.name} → {pack_size} {consumable.unit_label}/{pack_label}')
        created += 1
    else:
        print(f'  · Exists:  {consumable.name}')
        skipped += 1

print(f'\nDone. Created:{created} | Skipped:{skipped} | Missing:{missing}')