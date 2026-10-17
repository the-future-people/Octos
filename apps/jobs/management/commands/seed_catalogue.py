"""
python manage.py seed_catalogue [--dry-run]

The Westland catalogue, loaded in agreed batches. Each batch is what
Khofi has confirmed, service by service; nothing here is a guess.

Safe to run again: it sets things to the agreed state rather than adding
to them. --dry-run shows what would change and keeps none of it.

Batch 1 (16 Oct 2026): the everyday prints online with their finishing
add-ons, business cards by the box, flexy and SAV.

Batch 3 (17 Oct 2026): minimums and finishing.
  - Flexy and SAV: at least GHS 30 an order line (not a piece), any size
    from 1in as typed.
  - SAV cut to shape is a choice, GHS 3 a sq ft, by hand until the plotter.
  - Flexy eyelets are a choice, free. Every banner is still trimmed.
  - Flyers: ten or more, and always cut on the guillotine, as part of the
    job rather than a charge.

Batch 2 (16 Oct 2026): one product per print, with the sides a choice
on it. The one-sided and two-sided services stay separate, each with
its own price, so the counter, the floor and the reports are unchanged;
the storefront shows the pair as one product.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

# Westland has no plotter yet. Until the ET680 arrives, SAV is cut by hand
# at the bench, which keeps it orderable. Set False to put the cut back on
# the plotter.
SAV_CUT_BY_HAND = True

ONLINE = [
    'A4-BW-PRINT-1S', 'A4-BW-PRINT-2S', 'A4-COL-PRINT-1S', 'A4CLRP2',
    'A3-COL-PRINT', 'A3CLRP2',
    'A4-FLYER', 'A4-FLYER-2-SIDED', 'A5-FLYER', 'A5-FLYER-2SIDED',
    'BIZ-CARDS', 'FLEXY', 'SAV',
]

# Packing add-ons. The existing envelope services are printed envelopes
# sold over the counter; putting a finished job into an envelope is
# packing, done at the bench.
NEW_ADDONS = [
    {'code': 'ENV-PACK-A4', 'name': 'Brown Envelope (packed)', 'price': Decimal('2.00'),
     'description': 'Your printed copies placed in an A4 brown envelope.'},
    # No price agreed yet, so it shows as unavailable until it has one.
    {'code': 'CLEAR-BAG', 'name': 'Clear Bag (packed)', 'price': None,
     'description': 'Your printed copies placed in a clear bag.'},
]

A4_DOCS = ['A4-LAM', 'A4-BIND', 'ENV-PACK-A4', 'CLEAR-BAG']
ADDONS = {
    'A4-BW-PRINT-1S':   A4_DOCS,
    'A4-BW-PRINT-2S':   A4_DOCS,
    'A4-COL-PRINT-1S':  A4_DOCS,
    'A4CLRP2':          A4_DOCS,
    'A3-COL-PRINT':     ['A3-LAM', 'A3-BIND', 'CLEAR-BAG'],
    'A3CLRP2':          ['A3-LAM', 'A3-BIND', 'CLEAR-BAG'],
    'A4-FLYER':         ['A4-LAM', 'ENV-PACK-A4', 'CLEAR-BAG'],
    'A4-FLYER-2-SIDED': ['A4-LAM', 'ENV-PACK-A4', 'CLEAR-BAG'],
    'A5-FLYER':         ['CLEAR-BAG'],
    'A5-FLYER-2SIDED':  ['CLEAR-BAG'],
    'BIZ-CARDS':        ['CLEAR-BAG'],
}

BUSINESS_CARDS = {
    'unit': 'PER_PIECE',
    'price': Decimal('150.00'),
    'description': 'A box of 100 cards, printed and cut. One side or both, the same price.',
    'spec_template': [
        {'key': 'quantity', 'type': 'number', 'label': 'Boxes of 100', 'unit': 'boxes',
         'min': 1, 'default': 1, 'required': True},
        {'key': 'sides', 'type': 'select', 'label': 'Sides', 'default': 'Double-sided',
         'options': ['Single-sided', 'Double-sided'], 'required': True},
    ],
    # Printed on the Canon, then cut by hand with the guillotine until a
    # card cutter arrives. Minutes are per box.
    'route': [
        ('PRINT', 'DIGITAL_PRESS', Decimal('5.00'), Decimal('2.000')),
        ('CUT',   None,            Decimal('5.00'), Decimal('8.000')),
    ],
}

PACK_ROUTE = ('FINISH', None, Decimal('0.00'), Decimal('0.500'))

# Fewest that can be ordered.
MIN_QUANTITY = {
    'A4-FLYER': 10, 'A4-FLYER-2-SIDED': 10,
    'A5-FLYER': 10, 'A5-FLYER-2SIDED': 10,
}

# Smallest side, in inches, a large-format piece may be typed at. Small
# pieces are not refused: the line minimum covers them.
MIN_SIDE_IN = {'FLEXY': 1, 'SAV': 1}

# The least an order line costs, however few or small the pieces.
LINE_MINIMUM = {'FLEXY': Decimal('30.00'), 'SAV': Decimal('30.00')}

# Finishing chosen per order. Cutting SAV is priced by area, like the
# print; eyelets are free, a choice so the bench knows which banners get
# them.
FINISHING = [
    {'code': 'SAV-CUT', 'name': 'Cut to shape', 'unit': 'PER_SQFT', 'price': Decimal('3.00'),
     'description': 'Each sticker cut out along its shape.',
     'for': 'SAV', 'route': ('CUT', 'PLOTTER', Decimal('5.00'), Decimal('2.000'))},
    {'code': 'EYELETS', 'name': 'Eyelets', 'unit': 'PER_PIECE', 'price': Decimal('0.00'),
     'description': 'Metal eyelets in the corners, ready to hang.',
     'for': 'FLEXY', 'route': ('FINISH', None, Decimal('0.00'), Decimal('3.000'))},
]

# Cut on the guillotine as part of the job: nobody is handed uncut flyers.
CUT_AS_PART_OF_JOB = ['A4-FLYER', 'A4-FLYER-2-SIDED', 'A5-FLYER', 'A5-FLYER-2SIDED']

# (front only, front and back, the name customers see)
SIDES = [
    ('A4-COL-PRINT-1S', 'A4CLRP2',          'A4 Colour Printing'),
    ('A4-BW-PRINT-1S',  'A4-BW-PRINT-2S',   'A4 Black & White Printing'),
    ('A3-COL-PRINT',    'A3CLRP2',          'A3 Colour Printing'),
    ('A4-FLYER',        'A4-FLYER-2-SIDED', 'A4 Flyers'),
    ('A5-FLYER',        'A5-FLYER-2SIDED',  'A5 Flyers'),
]


class DryRun(Exception):
    pass


class Command(BaseCommand):
    help = 'Loads the agreed Westland catalogue batches.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show the changes, keep none.')

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                self._batch_1()
                self._batch_2()
                self._batch_3()
                if options['dry_run']:
                    raise DryRun()
        except DryRun:
            self.stdout.write(self.style.WARNING('Dry run: nothing was kept.'))
            return
        self.stdout.write(self.style.SUCCESS('Batches 1 to 3 loaded.'))

    # ── helpers ──────────────────────────────────────────────────
    def say(self, text):
        self.stdout.write(f'  {text}')

    def _rule(self, service, price):
        """One active default price for the service, at the agreed figure."""
        from apps.jobs.models import PricingRule
        rule = PricingRule.objects.filter(service=service, branch__isnull=True, is_active=True).first()
        if rule is None:
            PricingRule.objects.create(service=service, branch=None, base_price=price, is_active=True)
            self.say(f'{service.code}: price set to {price}')
        elif rule.base_price != price:
            self.say(f'{service.code}: price {rule.base_price} -> {price}')
            rule.base_price = price
            rule.save(update_fields=['base_price'])

    def _route(self, service, steps):
        """The service's route, exactly these steps."""
        from apps.production.models import MachineType, ServiceStation, Station
        ServiceStation.objects.filter(service=service).delete()
        for sequence, (station, machine_type, setup, per_unit) in enumerate(steps, 1):
            ServiceStation.objects.create(
                service=service,
                station=Station.objects.get(code=station),
                machine_type=MachineType.objects.get(code=machine_type) if machine_type else None,
                sequence=sequence,
                setup_minutes=setup,
                minutes_per_unit=per_unit,
            )
        self.say(f'{service.code}: route ' + ' > '.join(
            f'{s}:{m or "hand"}' for s, m, _, _ in steps))

    # ── batch 1 ──────────────────────────────────────────────────
    def _batch_1(self):
        from apps.jobs.models import Service
        from apps.production.models import ServiceStation

        self.stdout.write('Batch 1')

        for spec in NEW_ADDONS:
            service, made = Service.objects.get_or_create(
                code=spec['code'],
                defaults={
                    'name': spec['name'], 'category': 'INSTANT', 'unit': 'PER_PIECE',
                    'description': spec['description'], 'is_active': True,
                },
            )
            if made:
                self.say(f'{service.code}: created')
            if spec['price'] is not None:
                self._rule(service, spec['price'])
            self._route(service, [PACK_ROUTE])

        cards = Service.objects.get(code='BIZ-CARDS')
        cards.unit = BUSINESS_CARDS['unit']
        cards.description = BUSINESS_CARDS['description']
        cards.spec_template = BUSINESS_CARDS['spec_template']
        cards.save(update_fields=['unit', 'description', 'spec_template'])
        self.say('BIZ-CARDS: sold by the box of 100')
        self._rule(cards, BUSINESS_CARDS['price'])
        self._route(cards, BUSINESS_CARDS['route'])

        if SAV_CUT_BY_HAND:
            n = ServiceStation.objects.filter(service__code='SAV', station__code='CUT').update(machine_type=None)
            if n:
                self.say('SAV: cut by hand until the plotter arrives')

        for code in ONLINE:
            service = Service.objects.get(code=code)
            if not service.online or not service.requires_file_upload:
                service.online = True
                service.requires_file_upload = True
                service.save(update_fields=['online', 'requires_file_upload'])
                self.say(f'{code}: online')

        for code, addon_codes in ADDONS.items():
            service = Service.objects.get(code=code)
            service.addons.set(Service.objects.filter(code__in=addon_codes))
            self.say(f'{code}: add-ons {", ".join(addon_codes)}')

    # ── batch 2 ──────────────────────────────────────────────────
    def _batch_2(self):
        from apps.jobs.models import Service

        self.stdout.write('Batch 2')
        for front, both, name in SIDES:
            one = Service.objects.get(code=front)
            two = Service.objects.get(code=both)

            one.display_name, one.variant_of, one.variant_label = name, None, 'Front only'
            one.save(update_fields=['display_name', 'variant_of', 'variant_label'])

            two.display_name, two.variant_of, two.variant_label = name, one, 'Front and back'
            two.save(update_fields=['display_name', 'variant_of', 'variant_label'])

            self.say(f'{name}: {front} front only, {both} front and back')

    # ── batch 3 ──────────────────────────────────────────────────
    def _batch_3(self):
        from apps.jobs.models import PricingRule, Service
        from apps.production.models import ServiceStation, Station

        self.stdout.write('Batch 3')

        for code, minimum in MIN_QUANTITY.items():
            service = Service.objects.get(code=code)
            template = [dict(f) for f in (service.spec_template or [])]
            field = next((f for f in template if f.get('key') == 'quantity'), None)
            if field is None:
                field = {'key': 'quantity', 'type': 'number', 'label': 'Quantity', 'required': True}
                template.insert(0, field)
            if field.get('min') != minimum:
                self.say(f'{code}: at least {minimum} (was {field.get("min") or 1})')
            field['min'] = minimum
            if (field.get('default') or 0) < minimum:
                field['default'] = minimum
            service.spec_template = template
            service.save(update_fields=['spec_template'])

        for code, smallest in MIN_SIDE_IN.items():
            service = Service.objects.get(code=code)
            template = [dict(f) for f in (service.spec_template or [])]
            for f in template:
                if f.get('key') in ('width_in', 'height_in') and f.get('min') != smallest:
                    self.say(f'{code}: {f["key"]} from {smallest}in (was {f.get("min")}in)')
                    f['min'] = smallest
            service.spec_template = template
            service.save(update_fields=['spec_template'])

        for code, minimum in LINE_MINIMUM.items():
            # Saved, not updated, so the price cache is cleared at once.
            for rule in PricingRule.objects.filter(service__code=code, is_active=True):
                if rule.minimum_price != minimum:
                    self.say(f'{code}: at least {minimum} an order line (was {rule.minimum_price} a piece)')
                    rule.minimum_price = minimum
                    rule.save()

        for spec in FINISHING:
            addon, made = Service.objects.get_or_create(
                code=spec['code'],
                defaults={'name': spec['name'], 'category': 'PRODUCTION', 'unit': spec['unit'],
                          'description': spec['description'], 'is_active': True},
            )
            if made:
                self.say(f'{addon.code}: created')
            self._rule(addon, spec['price'])
            station, machine, setup, per_unit = spec['route']
            if spec['code'] == 'SAV-CUT' and SAV_CUT_BY_HAND:
                machine = None
            self._route(addon, [(station, machine, setup, per_unit)])
            parent = Service.objects.get(code=spec['for'])
            parent.addons.add(addon)
            self.say(f'{parent.code}: offers {addon.name}')

        # The base routes lose what became a choice: SAV's cut, flexy's
        # finishing bench. Flexy keeps its trim.
        n = ServiceStation.objects.filter(service__code='SAV', station__code='CUT').delete()[0]
        if n:
            self.say('SAV: cutting is now a choice, not on every order')
        n = ServiceStation.objects.filter(service__code='FLEXY', station__code='FINISH').delete()[0]
        if n:
            self.say('FLEXY: eyelets are now a choice; every banner is still trimmed')

        cut = Station.objects.get(code='CUT')
        for code in CUT_AS_PART_OF_JOB:
            service = Service.objects.get(code=code)
            routes = ServiceStation.objects.filter(service=service)
            if not routes.filter(station=cut).exists():
                last = max([r.sequence for r in routes] or [0])
                ServiceStation.objects.create(
                    service=service, station=cut, machine_type=None, sequence=last + 1,
                    setup_minutes=Decimal('3.00'), minutes_per_unit=Decimal('0.050'),
                )
                self.say(f'{code}: cut on the guillotine as part of the job')