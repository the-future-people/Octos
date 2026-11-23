"""
Graphic design in the catalogue (23 Nov 2026). A customer asked Octos for a
roll-up banner designed from her documents, and Octos had no design service
to quote, so it said "I can't see a design service on my side" and handed
over. Khofi's prices:

  GHS 150   we design it and print it (the printing is priced on top)
  GHS 300   we design it and hand over the complete file, to print anywhere

One product with two versions, like front only / front and back. A flat
price for the job, no machine on the route, so it is available as soon as
it has its price. Counter and WhatsApp only, not on Print Octos yet.
"""
from decimal import Decimal

from django.db import migrations

WITH_PRINT = {
    'code': 'DESIGN-PRINT',
    'name': 'Graphic Design',
    'variant_label': 'Printed with us',
    'price': Decimal('150.00'),
    'description': (
        'We design the artwork (a flyer, banner, roll-up, card, poster or programme) from the '
        "customer's information and photos, and print it here. GHS 150 for the design, plus the "
        'price of the printing.'
    ),
}
FILE_ONLY = {
    'code': 'DESIGN-FILE',
    'name': 'Graphic Design, complete file',
    'variant_label': 'Design and complete file',
    'price': Decimal('300.00'),
    'description': (
        'We design the artwork and give the customer the complete, print-ready file to use or print '
        'anywhere. GHS 300, no printing included.'
    ),
}


def _put(Service, PricingRule, spec, parent=None):
    service = (Service.objects.filter(code=spec['code']).first()
               or Service.objects.filter(name=spec['name']).first()
               or Service(code=spec['code']))
    service.code = spec['code']
    service.name = spec['name']
    service.category = 'DESIGN'
    service.unit = 'PER_JOB'
    service.description = spec['description']
    service.variant_label = spec['variant_label']
    service.variant_of = parent
    service.requires_design = True
    service.requires_file_upload = False
    service.is_active = True
    service.online = False
    service.save()
    PricingRule.objects.update_or_create(
        service=service, branch=None,
        defaults={'base_price': spec['price'], 'is_active': True, 'minimum_price': Decimal('0')},
    )
    return service


def add(apps, schema_editor):
    Service = apps.get_model('jobs', 'Service')
    PricingRule = apps.get_model('jobs', 'PricingRule')
    parent = _put(Service, PricingRule, WITH_PRINT)
    _put(Service, PricingRule, FILE_ONLY, parent=parent)


def remove(apps, schema_editor):
    Service = apps.get_model('jobs', 'Service')
    Service.objects.filter(code__in=[WITH_PRINT['code'], FILE_ONLY['code']]).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [('jobs', '0057_job_trade_partner')]

    operations = [migrations.RunPython(add, remove)]
