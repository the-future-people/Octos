"""
Octos — Seed Corrections (Fixed v2)
Run inside Django shell: exec(open('seed_corrections.py').read())
"""

from apps.jobs.models import Service, PricingRule
from apps.inventory.models import ConsumableItem, ConsumableCategory, ServiceConsumable, BranchStock
from apps.organization.models import Branch
from django.db import transaction

def get_or_create_category(name):
    cat, created = ConsumableCategory.objects.get_or_create(name=name)
    print(f"  {'[+]' if created else '[=]'} Category: {name}")
    return cat

def get_or_create_consumable(name, category_obj, unit_type, reorder_point=10):
    c, created = ConsumableItem.objects.get_or_create(
        name=name,
        defaults={'category': category_obj, 'unit_type': unit_type, 'reorder_point': reorder_point}
    )
    print(f"  {'[+]' if created else '[=]'} Consumable: {name}")
    return c

def ensure_branch_stock(consumable):
    for branch in Branch.objects.all():
        _, created = BranchStock.objects.get_or_create(
            branch=branch, consumable=consumable,
            defaults={'quantity': 0}
        )
        if created:
            print(f"      Stock → {branch.code}")

def get_or_create_service(name, category, unit, code, description=''):
    s, created = Service.objects.get_or_create(
        name=name,
        defaults={'category': category, 'unit': unit, 'code': code,
                  'description': description, 'is_active': True}
    )
    print(f"  {'[+]' if created else '[=]'} Service: {name}")
    return s, created

def set_price(service, price):
    from decimal import Decimal
    price = Decimal(str(price))
    rule = service.pricing_rules.first()
    if rule:
        if rule.base_price != price:
            rule.base_price = price
            rule.save(update_fields=['base_price'])
            print(f"      Price updated → GHS {price}")
    else:
        PricingRule.objects.create(service=service, base_price=price)
        print(f"      Price set → GHS {price}")

def wire_consumable(service, consumable, qty):
    sc, created = ServiceConsumable.objects.get_or_create(
        service=service, consumable=consumable,
        defaults={'quantity_per_unit': qty, 'applies_to_color': True, 'applies_to_bw': True}
    )
    print(f"      {'Wired' if created else 'Already wired'}: {consumable.name} x{qty}")
    return sc

with transaction.atomic():

    print("\n=== STEP 0 — Categories ===")
    cat_binding     = ConsumableCategory.objects.get(id=3)
    cat_photography = get_or_create_category('Photography')
    cat_machinery   = get_or_create_category('Machinery')

    print("\n=== STEP 1 — Binding consumables ===")
    a4_film  = get_or_create_consumable('A4 Binding Film',  cat_binding, 'UNITS', 20)
    a3_film  = get_or_create_consumable('A3 Binding Film',  cat_binding, 'UNITS', 10)
    a4_cover = get_or_create_consumable('A4 Binding Cover', cat_binding, 'UNITS', 20)
    a3_cover = get_or_create_consumable('A3 Binding Cover', cat_binding, 'UNITS', 10)
    for c in [a4_film, a3_film, a4_cover, a3_cover]:
        ensure_branch_stock(c)

    existing_rings = {c.name: c for c in ConsumableItem.objects.filter(category=cat_binding, name__icontains='Binding Ring')}
    rings = {}
    print("  Ring sizes:")
    for mm in [6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36]:
        name = f'Binding Rings {mm}mm'
        if name in existing_rings:
            rings[mm] = existing_rings[name]
            print(f"  [=] Exists: {name}")
        else:
            rings[mm] = get_or_create_consumable(name, cat_binding, 'UNITS', 10)
            ensure_branch_stock(rings[mm])

    print("\n=== STEP 2 — Passport Photo Film ===")
    passport_film = get_or_create_consumable('Passport Photo Film', cat_photography, 'UNITS', 5)
    ensure_branch_stock(passport_film)

    print("\n=== STEP 3 — Machinery ===")
    for name in [
        'Canon iR-ADV 5531i Printer', 'Dell 15" Monitor',
        'System Unit (Desktop PC)', 'MasterPlus A4/A3 Laminator',
        'MasterPlus Binding Machine', 'Canon SELPHY CP1000',
        'Huawei Broadband Receiver',
    ]:
        ensure_branch_stock(get_or_create_consumable(name, cat_machinery, 'UNITS', 1))

    print("\n=== STEP 4 — Fix Scanning ===")
    try:
        s = Service.objects.get(name='Scanning')
        s.name = 'A4 Scanning'; s.code = 'A4-SCAN'
        s.save(update_fields=['name', 'code'])
        print("  [~] Renamed: Scanning → A4 Scanning")
        a4_scan = s
    except Service.DoesNotExist:
        a4_scan, _ = get_or_create_service('A4 Scanning', 'INSTANT', 'PER_COPY', 'A4-SCAN')
    set_price(a4_scan, 1.00)
    a3_scan, _ = get_or_create_service('A3 Scanning', 'INSTANT', 'PER_COPY', 'A3-SCAN', 'Scan a single A3 document')
    set_price(a3_scan, 2.00)

    print("\n=== STEP 5 — Fix Binding ===")
    try:
        s = Service.objects.get(name='Binding')
        s.name = 'A4 Binding'; s.code = 'A4-BIND'
        s.save(update_fields=['name', 'code'])
        print("  [~] Renamed: Binding → A4 Binding")
        a4_bind = s
    except Service.DoesNotExist:
        a4_bind, _ = get_or_create_service('A4 Binding', 'INSTANT', 'PER_JOB', 'A4-BIND')
    set_price(a4_bind, 10.00)
    a3_bind, _ = get_or_create_service('A3 Binding', 'INSTANT', 'PER_JOB', 'A3-BIND', 'Bind an A3 document')
    set_price(a3_bind, 20.00)

    print("\n=== STEP 6 — Wire Binding consumables ===")
    print("  A4 Binding:")
    wire_consumable(a4_bind, a4_film, 1)
    wire_consumable(a4_bind, a4_cover, 1)
    wire_consumable(a4_bind, rings[10], 1)
    print("  A3 Binding:")
    wire_consumable(a3_bind, a3_film, 1)
    wire_consumable(a3_bind, a3_cover, 1)
    wire_consumable(a3_bind, rings[10], 1)

    print("\n=== STEP 7 — Wire Passport → Film ===")
    for svc in Service.objects.filter(name__icontains='passport'):
        print(f"  {svc.name}:")
        wire_consumable(svc, passport_film, 1)

    print(f"\n=== DONE ===")
    print(f"  Categories:  {ConsumableCategory.objects.count()}")
    print(f"  Consumables: {ConsumableItem.objects.count()}")
    print(f"  Services:    {Service.objects.count()}")
    print(f"  Mappings:    {ServiceConsumable.objects.count()}")