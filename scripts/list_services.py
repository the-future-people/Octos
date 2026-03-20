from apps.jobs.models import Service, PricingRule
for s in Service.objects.filter(category='INSTANT').order_by('name'):
    rule  = PricingRule.objects.filter(service=s, branch__isnull=True, is_active=True).first()
    price = str(rule.base_price) if rule else 'NO RULE'
    print('  ' + s.name.ljust(42) + ' | ' + s.unit.ljust(6) + ' | GHS ' + price)
