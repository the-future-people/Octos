"""
Seed ServiceConsumable mappings.
Run via: Get-Content seed_service_consumables.py | python manage.py shell

Maps each service to the consumables it uses per unit of work.
quantity_per_unit = consumable units used per 1 page * sets of the service.

Toner deduction: 0.01% per page (100 pages = 1% toner)
Paper deduction: 1 sheet per page per set
"""

from apps.inventory.models import ServiceConsumable
from apps.jobs.models import Service
from apps.inventory.models import ConsumableItem

def get_service(code):
    try:
        return Service.objects.get(code=code)
    except Service.DoesNotExist:
        print(f'  MISSING service: {code}')
        return None

def get_consumable(name):
    try:
        return ConsumableItem.objects.get(name=name)
    except ConsumableItem.DoesNotExist:
        print(f'  MISSING consumable: {name}')
        return None

def map_service(service_code, consumable_name, qty_per_unit,
                applies_to_color=True, applies_to_bw=True):
    svc = get_service(service_code)
    con = get_consumable(consumable_name)
    if not svc or not con:
        return

    obj, created = ServiceConsumable.objects.get_or_create(
        service    = svc,
        consumable = con,
        defaults   = {
            'quantity_per_unit': qty_per_unit,
            'applies_to_color' : applies_to_color,
            'applies_to_bw'    : applies_to_bw,
        }
    )
    status = 'CREATED' if created else 'EXISTS'
    print(f'  [{status}] {svc.name} → {con.name} ({qty_per_unit}/unit)')

print('Seeding ServiceConsumable mappings...')

# ── A4 B&W Printing ───────────────────────────────────────────
# 1 sheet of A4 paper per page, 0.01% black toner per page
map_service('A4-BW-PRINT-1S', 'A4 Paper 80gsm',         1.0,  applies_to_color=False, applies_to_bw=True)
map_service('A4-BW-PRINT-1S', 'Canon 5535i Toner Black', 0.01, applies_to_color=False, applies_to_bw=True)
map_service('A4-BW-PRINT-2S', 'A4 Paper 80gsm',         1.0,  applies_to_color=False, applies_to_bw=True)
map_service('A4-BW-PRINT-2S', 'Canon 5535i Toner Black', 0.01, applies_to_color=False, applies_to_bw=True)

# ── A4 B&W Photocopy ──────────────────────────────────────────
map_service('A4-BW-COPY-1S', 'A4 Paper 80gsm',          1.0,  applies_to_color=False, applies_to_bw=True)
map_service('A4-BW-COPY-1S', 'Canon 5535i Toner Black',  0.01, applies_to_color=False, applies_to_bw=True)
map_service('A4-BW-COPY-2S', 'A4 Paper 80gsm',          1.0,  applies_to_color=False, applies_to_bw=True)
map_service('A4-BW-COPY-2S', 'Canon 5535i Toner Black',  0.01, applies_to_color=False, applies_to_bw=True)

# ── A4 Color Printing ─────────────────────────────────────────
# 1 sheet + all 4 toners (0.01% each per page)
map_service('A4-COL-PRINT-1S', 'A4 Paper 80gsm',          1.0,  applies_to_color=True, applies_to_bw=False)
map_service('A4-COL-PRINT-1S', 'Canon 5535i Toner Black',  0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4-COL-PRINT-1S', 'Canon 5535i Toner Cyan',   0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4-COL-PRINT-1S', 'Canon 5535i Toner Magenta',0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4-COL-PRINT-1S', 'Canon 5535i Toner Yellow', 0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4CLRP2', 'A4 Paper 80gsm',                   1.0,  applies_to_color=True, applies_to_bw=False)
map_service('A4CLRP2', 'Canon 5535i Toner Black',           0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4CLRP2', 'Canon 5535i Toner Cyan',            0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4CLRP2', 'Canon 5535i Toner Magenta',         0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4CLRP2', 'Canon 5535i Toner Yellow',          0.01, applies_to_color=True, applies_to_bw=False)

# ── A4 Color Photocopy ────────────────────────────────────────
map_service('A4-COL-COPY-1S', 'A4 Paper 80gsm',           1.0,  applies_to_color=True, applies_to_bw=False)
map_service('A4-COL-COPY-1S', 'Canon 5535i Toner Black',   0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4-COL-COPY-1S', 'Canon 5535i Toner Cyan',    0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4-COL-COPY-1S', 'Canon 5535i Toner Magenta', 0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4-COL-COPY-1S', 'Canon 5535i Toner Yellow',  0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4CLRC2', 'A4 Paper 80gsm',                   1.0,  applies_to_color=True, applies_to_bw=False)
map_service('A4CLRC2', 'Canon 5535i Toner Black',           0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4CLRC2', 'Canon 5535i Toner Cyan',            0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4CLRC2', 'Canon 5535i Toner Magenta',         0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4CLRC2', 'Canon 5535i Toner Yellow',          0.01, applies_to_color=True, applies_to_bw=False)

# ── A3 B&W Printing ───────────────────────────────────────────
map_service('A3-BW-PRINT', 'A3 Paper 80gsm',          1.0,  applies_to_color=False, applies_to_bw=True)
map_service('A3-BW-PRINT', 'Canon 5535i Toner Black',  0.02, applies_to_color=False, applies_to_bw=True)
map_service('A3BWP2',      'A3 Paper 80gsm',          1.0,  applies_to_color=False, applies_to_bw=True)
map_service('A3BWP2',      'Canon 5535i Toner Black',  0.02, applies_to_color=False, applies_to_bw=True)

# ── A3 B&W Photocopy ──────────────────────────────────────────
map_service('A3-BW-COPY', 'A3 Paper 80gsm',           1.0,  applies_to_color=False, applies_to_bw=True)
map_service('A3-BW-COPY', 'Canon 5535i Toner Black',   0.02, applies_to_color=False, applies_to_bw=True)
map_service('A3BWC2',     'A3 Paper 80gsm',            1.0,  applies_to_color=False, applies_to_bw=True)
map_service('A3BWC2',     'Canon 5535i Toner Black',    0.02, applies_to_color=False, applies_to_bw=True)

# ── A3 Color Printing ─────────────────────────────────────────
map_service('A3-COL-PRINT', 'A3 Paper 80gsm',            1.0,  applies_to_color=True, applies_to_bw=False)
map_service('A3-COL-PRINT', 'Canon 5535i Toner Black',    0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3-COL-PRINT', 'Canon 5535i Toner Cyan',     0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3-COL-PRINT', 'Canon 5535i Toner Magenta',  0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3-COL-PRINT', 'Canon 5535i Toner Yellow',   0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3CLRP2',      'A3 Paper 80gsm',             1.0,  applies_to_color=True, applies_to_bw=False)
map_service('A3CLRP2',      'Canon 5535i Toner Black',     0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3CLRP2',      'Canon 5535i Toner Cyan',      0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3CLRP2',      'Canon 5535i Toner Magenta',   0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3CLRP2',      'Canon 5535i Toner Yellow',    0.02, applies_to_color=True, applies_to_bw=False)

# ── A3 Color Photocopy ────────────────────────────────────────
map_service('A3-COL-COPY', 'A3 Paper 80gsm',             1.0,  applies_to_color=True, applies_to_bw=False)
map_service('A3-COL-COPY', 'Canon 5535i Toner Black',     0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3-COL-COPY', 'Canon 5535i Toner Cyan',      0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3-COL-COPY', 'Canon 5535i Toner Magenta',   0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3-COL-COPY', 'Canon 5535i Toner Yellow',    0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3CLRC2',     'A3 Paper 80gsm',              1.0,  applies_to_color=True, applies_to_bw=False)
map_service('A3CLRC2',     'Canon 5535i Toner Black',      0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3CLRC2',     'Canon 5535i Toner Cyan',       0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3CLRC2',     'Canon 5535i Toner Magenta',    0.02, applies_to_color=True, applies_to_bw=False)
map_service('A3CLRC2',     'Canon 5535i Toner Yellow',     0.02, applies_to_color=True, applies_to_bw=False)

# ── Lamination ────────────────────────────────────────────────
# 1 pouch per set
map_service('A4-LAM', 'A4 Lamination Pouches', 1.0)
map_service('A3-LAM', 'A3 Lamination Pouches', 1.0)

# ── Envelopes ─────────────────────────────────────────────────
# 1 envelope per set
map_service('A4-ENV', 'A4 Brown Envelope', 1.0)

# ── Binding ───────────────────────────────────────────────────
# 1 binding ring per job (quantity_per_unit=1, deducted once per set)
map_service('BINDING', 'Binding Rings 8mm', 1.0)

# ── Art Card Certificates ─────────────────────────────────────
map_service('A4AC1', 'A4 Shiny Card',              1.0,  applies_to_color=True, applies_to_bw=False)
map_service('A4AC1', 'Canon 5535i Toner Black',    0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4AC1', 'Canon 5535i Toner Cyan',     0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4AC1', 'Canon 5535i Toner Magenta',  0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4AC1', 'Canon 5535i Toner Yellow',   0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4AC2', 'A4 Shiny Card',              1.0,  applies_to_color=True, applies_to_bw=False)
map_service('A4AC2', 'Canon 5535i Toner Black',    0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4AC2', 'Canon 5535i Toner Cyan',     0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4AC2', 'Canon 5535i Toner Magenta',  0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4AC2', 'Canon 5535i Toner Yellow',   0.01, applies_to_color=True, applies_to_bw=False)

# ── Shiny Certificates ────────────────────────────────────────
map_service('A4SC1', 'A4 Certificate Paper',       1.0,  applies_to_color=True, applies_to_bw=False)
map_service('A4SC1', 'Canon 5535i Toner Black',    0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4SC1', 'Canon 5535i Toner Cyan',     0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4SC1', 'Canon 5535i Toner Magenta',  0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4SC1', 'Canon 5535i Toner Yellow',   0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4SC2', 'A4 Certificate Paper',       1.0,  applies_to_color=True, applies_to_bw=False)
map_service('A4SC2', 'Canon 5535i Toner Black',    0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4SC2', 'Canon 5535i Toner Cyan',     0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4SC2', 'Canon 5535i Toner Magenta',  0.01, applies_to_color=True, applies_to_bw=False)
map_service('A4SC2', 'Canon 5535i Toner Yellow',   0.01, applies_to_color=True, applies_to_bw=False)

# ── No consumable mapping needed ──────────────────────────────
# Banner, Business Cards, ID Card, Passport Photos,
# Scanning, Typing, Logo Design — no stock deducted
print('\nSkipped (no consumable): BANNER, BIZ-CARDS, ID-CARD, PP-US, PP-BR, PP-CA, SCAN, TYPING, LOGO')
print('\nDone.')