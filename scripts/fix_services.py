from apps.jobs.models import Service, PricingRule

defaults_map = {
    'A3BWC2' : {'paper_size': 'A3', 'is_color': False, 'sides': 'DOUBLE', 'quantity': 1, 'sets': 1, 'pages': 1},
    'A3BWP2' : {'paper_size': 'A3', 'is_color': False, 'sides': 'DOUBLE', 'quantity': 1, 'sets': 1, 'pages': 1},
    'A3CLRC2': {'paper_size': 'A3', 'is_color': True,  'sides': 'DOUBLE', 'quantity': 1, 'sets': 1, 'pages': 1},
    'A3CLRP2': {'paper_size': 'A3', 'is_color': True,  'sides': 'DOUBLE', 'quantity': 1, 'sets': 1, 'pages': 1},
    'A4CLRC2': {'paper_size': 'A4', 'is_color': True,  'sides': 'DOUBLE', 'quantity': 1, 'sets': 1, 'pages': 1},
    'A4CLRP2': {'paper_size': 'A4', 'is_color': True,  'sides': 'DOUBLE', 'quantity': 1, 'sets': 1, 'pages': 1},
    'A4SC1'  : {'paper_size': 'A4', 'is_color': True,  'sides': 'SINGLE', 'quantity': 1, 'sets': 1, 'pages': 1},
    'A4SC2'  : {'paper_size': 'A4', 'is_color': True,  'sides': 'DOUBLE', 'quantity': 1, 'sets': 1, 'pages': 1},
    'A4AC1'  : {'paper_size': 'A4', 'is_color': True,  'sides': 'SINGLE', 'quantity': 1, 'sets': 1, 'pages': 1},
    'A4AC2'  : {'paper_size': 'A4', 'is_color': True,  'sides': 'DOUBLE', 'quantity': 1, 'sets': 1, 'pages': 1},
    'SCAN'   : {'paper_size': 'A4', 'is_color': False, 'sides': 'SINGLE', 'quantity': 1, 'sets': 1, 'pages': 1},
}
for code, d in defaults_map.items():
    n = Service.objects.filter(code=code).update(smart_defaults=d)
    status = 'OK' if n else 'NOT FOUND'
    print(code + ': ' + status)

print('')
print('=== FINAL SERVICE LIST ===')
for s in Service.objects.filter(category='INSTANT').order_by('name'):
    rule  = PricingRule.objects.filter(service=s, branch__isnull=True, is_active=True).first()
    price = str(rule.base_price) if rule else 'NO RULE'
    print('  ' + s.name.ljust(42) + ' | ' + s.unit.ljust(6) + ' | GHS ' + price)
