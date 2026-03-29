from apps.jobs.models import Service, PricingRule
from django.db import transaction

with transaction.atomic():
    binding_tiers = [
        {"condition": "ring_size", "min": 6,  "max": 24, "flat_price": 10.00},
        {"condition": "ring_size", "min": 26, "max": 36, "flat_price": 25.00},
    ]
    for name in ['A4 Binding', 'A3 Binding']:
        svc = Service.objects.get(name=name)
        count = PricingRule.objects.filter(service=svc).update(pricing_tiers=binding_tiers)
        print(f"  {name}: updated {count} rules")

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
        svc   = Service.objects.get(name=name)
        count = PricingRule.objects.filter(service=svc).update(pricing_tiers=tiers)
        print(f"  {name}: updated {count} rules")

print("Done")