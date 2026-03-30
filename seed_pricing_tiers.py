"""
Octos — Conditional Pricing Tiers Seed
Run inside Django shell: exec(open('seed_pricing_tiers.py').read())

Adds pricing_tiers JSON to:
- A4 Binding, A3 Binding — ring size based (6-24 = GHS 10, 26-36 = GHS 25)
- Passport Photo (British, American, Canadian) — output mode based
  (PRINT/PRINT_DIGITAL = type price, DIGITAL = GHS 20)
"""

from apps.jobs.models import Service, PricingRule
from django.db import transaction

with transaction.atomic():

    print("\n=== Binding Pricing Tiers ===")

    binding_tiers = [
        {"condition": "ring_size", "min": 6,  "max": 24, "flat_price": 10.00},
        {"condition": "ring_size", "min": 26, "max": 36, "flat_price": 25.00},
    ]

    for name in ['A4 Binding', 'A3 Binding']:
        try:
            svc  = Service.objects.get(name=name)
            rule = svc.pricing_rules.first()
            if rule:
                rule.pricing_tiers = binding_tiers
                rule.save(update_fields=['pricing_tiers'])
                print(f"  [✓] {name} — tiers set")
            else:
                print(f"  [!] {name} — no pricing rule found")
        except Service.DoesNotExist:
            print(f"  [!] {name} — service not found")

    print("\n=== Passport Photo Pricing Tiers ===")

    passport_prices = {
        'Passport Photo (British)' : 30.00,
        'Passport Photo (American)': 50.00,
        'Passport Photo (Canadian)': 50.00,
    }

    for name, print_price in passport_prices.items():
        tiers = [
            {"condition": "output_mode", "value": "PRINT",         "flat_price": print_price},
            {"condition": "output_mode", "value": "PRINT_DIGITAL", "flat_price": print_price},
            {"condition": "output_mode", "value": "DIGITAL",       "flat_price": 20.00},
        ]
        try:
            svc  = Service.objects.get(name=name)
            rule = svc.pricing_rules.first()
            if rule:
                rule.pricing_tiers = tiers
                rule.save(update_fields=['pricing_tiers'])
                print(f"  [✓] {name} — tiers set (print: GHS {print_price}, digital: GHS 20)")
            else:
                print(f"  [!] {name} — no pricing rule found")
        except Service.DoesNotExist:
            print(f"  [!] {name} — service not found")

    print("\n=== Verify ===")
    for name in ['A4 Binding', 'A3 Binding',
                 'Passport Photo (British)', 'Passport Photo (American)',
                 'Passport Photo (Canadian)']:
        try:
            svc  = Service.objects.get(name=name)
            rule = svc.pricing_rules.first()
            tiers = rule.pricing_tiers if rule else None
            print(f"  {name}: {len(tiers)} tiers" if tiers else f"  {name}: NO TIERS")
        except Service.DoesNotExist:
            print(f"  {name}: NOT FOUND")

    print("\n=== DONE ===")