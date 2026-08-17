"""
Seed the route each service takes through the stations, with seed timings.

A service's route is only its own work. Binding is BIND, not PRINT then
BIND — if the document is being printed on the same job, that is a separate
line item carrying its own PRINT step. A job's route is the union of its
line items' routes.

The time figures are a starting guess, not a measurement. They are derived
from the C5535i's rated speed with a deliberate buffer, because a published
speed is a laboratory number: simplex, plain paper, from tray, no
finishing. Real throughput on heavier stock or with finishing is slower,
and the gap varies by job type. StationTiming corrects these per branch as
real work flows through — that correction is the point, and these numbers
exist only so there is something to correct.

Idempotent. Re-running adds missing routes and leaves existing ones alone,
so a hand-corrected time is never overwritten by a re-seed.

    python manage.py seed_service_routes
    python manage.py seed_service_routes --show
"""

from django.core.management.base import BaseCommand
from django.db import transaction


# Rated ~55ppm A4 simplex. Buffered heavily: at 55ppm a sheet is 1.1
# seconds, which is nothing like what a real job averages once stock,
# duplex, jams and someone walking to the machine are counted.
PRINT_SETUP    = 2.0     # minutes to set up a print job
PRINT_PER_UNIT = 0.05    # 3 seconds a sheet — roughly a third of rated

# code → (station, machine_type or None, setup, per_unit)
ROUTES = {
    'PRINT_SIMPLE':  ('PRINT',    'DIGITAL_PRESS', PRINT_SETUP, PRINT_PER_UNIT),
    'PRINT_HEAVY':   ('PRINT',    'DIGITAL_PRESS', 3.0,  0.12),   # card, certificates
    'PRINT_PHOTO':   ('PRINT',    'DIGITAL_PRESS', 3.0,  0.25),   # photo paper, care
    'SCAN':          ('PRINT',    'DIGITAL_PRESS', 1.5,  0.04),
    'LAMINATE':      ('LAMINATE', 'LAMINATOR',     1.0,  0.35),
    'BIND':          ('BIND',     'BINDER',        2.0,  2.50),   # per document
    'CUT':           ('CUT',      None,            1.0,  0.20),   # by hand today
    'HAND':          ('FINISH',   None,            0.0,  5.00),   # typing, design
}

# service id → list of route codes, in order
SERVICE_ROUTES = {
    # ── Plain printing and photocopy ──────────────────────────
    12: ['PRINT_SIMPLE'],  13: ['PRINT_SIMPLE'],  14: ['PRINT_SIMPLE'],
    15: ['PRINT_SIMPLE'],  27: ['PRINT_SIMPLE'],  29: ['PRINT_SIMPLE'],
    31: ['PRINT_SIMPLE'],  32: ['PRINT_SIMPLE'],
    6:  ['PRINT_SIMPLE'],  7:  ['PRINT_SIMPLE'],  8:  ['PRINT_SIMPLE'],
    9:  ['PRINT_SIMPLE'],  10: ['PRINT_SIMPLE'],  11: ['PRINT_SIMPLE'],
    33: ['PRINT_SIMPLE'],  34: ['PRINT_SIMPLE'],

    # ── Envelopes — awkward stock, fed carefully ──────────────
    21: ['PRINT_HEAVY'],   22: ['PRINT_HEAVY'],   56: ['PRINT_HEAVY'],
    57: ['PRINT_HEAVY'],   58: ['PRINT_HEAVY'],   50: ['PRINT_HEAVY'],

    # ── Card and certificates ─────────────────────────────────
    55: ['PRINT_HEAVY'],   37: ['PRINT_HEAVY'],   38: ['PRINT_HEAVY'],
    35: ['PRINT_HEAVY'],   36: ['PRINT_HEAVY'],   51: ['PRINT_HEAVY'],

    # ── Flyers ────────────────────────────────────────────────
    43: ['PRINT_SIMPLE'],  52: ['PRINT_SIMPLE'],
    44: ['PRINT_SIMPLE'],  46: ['PRINT_SIMPLE'],

    # ── Photo ─────────────────────────────────────────────────
    53: ['PRINT_PHOTO'],   54: ['PRINT_PHOTO'],

    # ── Passport photos — printed then cut ────────────────────
    40: ['PRINT_PHOTO', 'CUT'],
    41: ['PRINT_PHOTO', 'CUT'],
    42: ['PRINT_PHOTO', 'CUT'],

    # ── Scanning — the press scans, nothing is printed ────────
    39: ['SCAN'],          48: ['SCAN'],

    # ── Finishing only. The customer may bring their own
    #    document, or it may be printed on the same job as a
    #    separate line item carrying its own PRINT step.
    19: ['LAMINATE'],      20: ['LAMINATE'],
    18: ['BIND'],          49: ['BIND'],

    # ── People, not machines ──────────────────────────────────
    17: ['HAND'],          26: ['HAND'],          45: ['HAND'],

    # ── Production. Outsourced today: no machine exists for
    #    these, so no branch can currently take them. When a
    #    large format printer is registered they light up.
    24: [],  # Banner Printing
    25: [],  # Business Cards
    23: [],  # ID Card Printing
}


class Command(BaseCommand):
    help = 'Seed service routes through production stations.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--show',
            action='store_true',
            help='Print what each service would get, and write nothing.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.jobs.models import Service
        from apps.production.models import Station, MachineType, ServiceStation

        show_only = options['show']

        stations = {s.code: s for s in Station.objects.all()}
        types    = {t.code: t for t in MachineType.objects.all()}
        if not stations:
            self.stdout.write(self.style.ERROR(
                'No stations. Run seed_production first.'
            ))
            return

        created = skipped = missing = 0

        for service_id, route_codes in sorted(SERVICE_ROUTES.items()):
            service = Service.objects.filter(pk=service_id).first()
            if not service:
                self.stdout.write(self.style.WARNING(
                    f'  service {service_id} not found — skipped'
                ))
                missing += 1
                continue

            if not route_codes:
                self.stdout.write(
                    f'  {service.name:<42} no route (outsourced)'
                )
                continue

            for sequence, code in enumerate(route_codes, start=1):
                station_code, type_code, setup, per_unit = ROUTES[code]

                if show_only:
                    self.stdout.write(
                        f'  {service.name:<42} {sequence}. {station_code:<9} '
                        f'setup {setup} + {per_unit}/unit'
                    )
                    continue

                _, was_created = ServiceStation.objects.get_or_create(
                    service=service,
                    station=stations[station_code],
                    defaults={
                        'machine_type':     types.get(type_code) if type_code else None,
                        'sequence':         sequence,
                        'setup_minutes':    setup,
                        'minutes_per_unit': per_unit,
                    },
                )
                if was_created:
                    created += 1
                else:
                    skipped += 1

        if show_only:
            self.stdout.write(self.style.WARNING(
                '\nDry run. Re-run without --show to write.'
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {created} route(s) created, {skipped} already existed, '
            f'{missing} service(s) not found.'
        ))