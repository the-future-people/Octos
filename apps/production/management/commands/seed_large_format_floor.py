"""
python manage.py seed_large_format_floor

The large-format machines and the route a banner takes through them.

Until now Octos knew about a Canon press, a laminator and a binder, and
nothing that prints a banner — so the two services the storefront
actually sells had no route through the floor at all, and no way to be
given a ready time.

The figures are the manufacturer's at the pass counts Farhat will run:
4 pass for flexy, which is read from across a road, and 6 pass for SAV,
which ends up on a window or a vehicle at arm's length. More passes
means more ink layers, less banding, proportionally slower.

    E1902 (1900mm, i3200 2H)   4 pass 39 m²/h   6 pass 32 m²/h
    E3202 (3200mm, i3200 2H)   4 pass 30 m²/h   6 pass 24 m²/h

Note the wider machine is the slower one per square metre — a longer
carriage travel on every pass. So the 6ft is the first choice and the
10ft is for work too wide for it, not for work in a hurry.

A manufacturer's figure assumes a machine that never pauses. Real
throughput is lower, which is what the setup minutes carry.

Safe to run repeatedly.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction


BRANCH_CODE = 'WLB'

# Manufacturer m²/h at the pass count each service runs, converted to
# minutes per square foot: 60 / (m²/h × 10.7639).
FLEXY_MIN_PER_SQFT = Decimal('0.143')   # 39 m²/h, 4 pass
SAV_MIN_PER_SQFT = Decimal('0.174')     # 32 m²/h, 6 pass

MACHINE_TYPES = [
    {
        'code': 'LARGE_FORMAT',
        'name': 'Large format printer',
        'station': 'PRINT',
        'max_width_mm': 3200,
    },
    {
        'code': 'PLOTTER',
        'name': 'Plotter',
        'station': 'CUT',
        'max_width_mm': 680,
    },
]

MACHINES = [
    {
        'name': 'Extreme E1902 (6ft)',
        'type': 'LARGE_FORMAT',
        'model_number': 'E1902',
        'notes': '1900mm, i3200 dual head. The first choice: quicker per '
                 'square metre than the 10ft.',
    },
    {
        'name': 'Extreme E3202 (10ft)',
        'type': 'LARGE_FORMAT',
        'model_number': 'E3202',
        'notes': '3200mm, i3200 dual head. For work too wide for the 6ft.',
    },
    {
        'name': 'Extreme ET680 cutter',
        'type': 'PLOTTER',
        'model_number': 'ET/ETC680',
        'notes': '680mm cutting width. Contour cuts stickers and decals; '
                 'anything wider is trimmed by hand.',
    },
]

# setup_minutes, minutes_per_unit — where the unit is a square foot for
# an area-priced service.
ROUTES = {
    'FLEXY': [
        {
            'station': 'PRINT', 'machine_type': 'LARGE_FORMAT', 'sequence': 1,
            # Load the roll, RIP the file, nozzle check, test strip.
            'setup': Decimal('12.00'), 'per_unit': FLEXY_MIN_PER_SQFT,
        },
        {
            'station': 'CUT', 'machine_type': None, 'sequence': 2,
            # Hand-cut. A banner is wider than the plotter, and the time
            # is the same whether it is six feet or sixteen.
            'setup': Decimal('10.00'), 'per_unit': Decimal('0.000'),
        },
        {
            'station': 'FINISH', 'machine_type': None, 'sequence': 3,
            # Hemming and eyelets, which grow with the perimeter.
            'setup': Decimal('5.00'), 'per_unit': Decimal('0.250'),
        },
    ],
    'SAV': [
        {
            'station': 'PRINT', 'machine_type': 'LARGE_FORMAT', 'sequence': 1,
            'setup': Decimal('12.00'), 'per_unit': SAV_MIN_PER_SQFT,
        },
        {
            'station': 'CUT', 'machine_type': 'PLOTTER', 'sequence': 2,
            # The plotter runs at 1000mm/s, so cutting is seconds. The
            # time here is loading, registration and weeding.
            'setup': Decimal('8.00'), 'per_unit': Decimal('0.400'),
        },
    ],
}


class Command(BaseCommand):
    help = 'Seeds the large-format machines and the route flexy and SAV take'

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.jobs.models import Service
        from apps.organization.models import Branch
        from apps.production.models import (
            Machine, MachineType, ServiceStation, Station,
        )

        branch = Branch.objects.filter(code=BRANCH_CODE).first()
        if branch is None:
            self.stderr.write(self.style.ERROR(
                f'Branch {BRANCH_CODE} not found — nothing seeded.'
            ))
            return

        stations = {s.code: s for s in Station.objects.all()}
        missing = {
            code for spec in MACHINE_TYPES for code in [spec['station']]
        } - set(stations)
        if missing:
            self.stderr.write(self.style.ERROR(
                f'Stations not set up: {sorted(missing)}. Seed those first.'
            ))
            return

        # ── Machine types ─────────────────────────────────────────────
        types = {}
        for spec in MACHINE_TYPES:
            machine_type, _ = MachineType.objects.update_or_create(
                code=spec['code'],
                defaults={
                    'name': spec['name'],
                    'station': stations[spec['station']],
                    'max_width_mm': spec['max_width_mm'],
                    'is_active': True,
                },
            )
            types[spec['code']] = machine_type
            self.stdout.write(
                f"{spec['code']}: max width {spec['max_width_mm']}mm"
            )

        # ── Machines ──────────────────────────────────────────────────
        for spec in MACHINES:
            machine, created = Machine.objects.update_or_create(
                branch=branch, name=spec['name'],
                defaults={
                    'machine_type': types[spec['type']],
                    'model_number': spec['model_number'],
                    'notes': spec['notes'],
                    'is_active': True,
                    'is_available': True,
                },
            )
            self.stdout.write(self.style.SUCCESS(
                f"{'Added' if created else 'Updated'} {machine.name}"
            ))

        # ── Routes ────────────────────────────────────────────────────
        for code, steps in ROUTES.items():
            service = Service.objects.filter(code=code).first()
            if service is None:
                self.stderr.write(self.style.WARNING(
                    f'Service {code} not found — skipped.'
                ))
                continue

            # Replaced rather than added to, so a changed route does not
            # leave the old steps behind for the engine to walk.
            ServiceStation.objects.filter(service=service).delete()

            for step in steps:
                ServiceStation.objects.create(
                    service=service,
                    station=stations[step['station']],
                    machine_type=types.get(step['machine_type'])
                    if step['machine_type'] else None,
                    sequence=step['sequence'],
                    setup_minutes=step['setup'],
                    minutes_per_unit=step['per_unit'],
                )

            total = sum(s['setup'] for s in steps)
            self.stdout.write(self.style.SUCCESS(
                f'{service.name}: {len(steps)} steps, {total} minutes of setup'
            ))

        self.stdout.write(self.style.SUCCESS('Floor seeding complete.'))