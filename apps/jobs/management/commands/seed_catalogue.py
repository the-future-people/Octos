"""
python manage.py seed_catalogue [--dry-run]

The Westland catalogue, loaded in agreed batches. Each batch is what
Khofi has confirmed, service by service; nothing here is a guess.

Safe to run again: it sets things to the agreed state rather than adding
to them. --dry-run shows what would change and keeps none of it.

Batch 1 (16 Oct 2026): the everyday prints online with their finishing
add-ons, business cards by the box, flexy and SAV.
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
                if options['dry_run']:
                    raise DryRun()
        except DryRun:
            self.stdout.write(self.style.WARNING('Dry run: nothing was kept.'))
            return
        self.stdout.write(self.style.SUCCESS('Batch 1 loaded.'))

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