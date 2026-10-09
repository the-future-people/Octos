"""
python manage.py seed_floor

The production floor: its stations, the classes of machine that work at
them, and the route each service takes through them.

All of this existed on the production database and nowhere else — set
up by hand, in no migration and no command. A rebuilt database would
have lost 49 service routes and the figures behind them, and the local
database never had them at all, so nothing touching the floor could be
exercised outside production.

The timings are what someone measured or judged on the floor. They are
not derived from anything here, so this file is their only record.

Safe to run repeatedly. Existing rows are updated, not duplicated.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction


# sequence, code, name — the order work passes through them.
STATIONS = [
    (1, 'PRINT', 'Printing'),
    (2, 'CUT', 'Cutting'),
    (3, 'LAMINATE', 'Laminating'),
    (4, 'BIND', 'Binding'),
    (5, 'FINISH', 'Hand finishing'),
]

# code, name, station, max_paper_size, max_width_mm
#
# A press is limited by sheet size and a roll printer by width, so the
# two fields answer different questions and both are kept.
# code, name, station, max_paper_size
#
# Width is not here: it belongs to the machine, since a 6ft and a 10ft
# roll printer are both large format and a route that named each width
# would rule out machines that could do the work.
MACHINE_TYPES = [
    ('DIGITAL_PRESS', 'Digital press',        'PRINT',    'A3'),
    ('LARGE_FORMAT',  'Large format printer', 'PRINT',    ''),
    ('PLOTTER',       'Plotter',              'CUT',      ''),
    ('CUTTER',        'Cutter',               'CUT',      'A3'),
    ('LAMINATOR',     'Laminator',            'LAMINATE', 'A3'),
    ('BINDER',        'Binding machine',      'BIND',     'A3'),
]

# service code, station, machine type, sequence, setup minutes,
# minutes per unit.
#
# The unit is a page or a piece for counted work, and a square foot for
# anything priced by area.
ROUTES = [
    ('A3-ART-CARD-1-SIDED',  'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.1200'),
    ('A3-BIND',              'BIND',     'BINDER',        1, '2.00', '2.5000'),
    ('A3-ENV',               'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.1200'),
    ('A3-BW-COPY',           'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A3BWC2',               'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A3-BW-PRINT',          'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A3BWP2',               'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A3-COL-COPY',          'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A3CLRC2',              'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A3-COL-PRINT',         'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A3CLRP2',              'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A3-LAM',               'LAMINATE', 'LAMINATOR',     1, '1.00', '0.3500'),
    ('A3-SCAN',              'PRINT',    'DIGITAL_PRESS', 1, '1.50', '0.0400'),
    ('A4AC1',                'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.1200'),
    ('A4AC2',                'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.1200'),
    ('A4-BIND',              'BIND',     'BINDER',        1, '2.00', '2.5000'),
    ('A4-ENV',               'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.1200'),
    ('A4-BW-COPY-1S',        'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A4-BW-COPY-2S',        'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A4-BW-PRINT-1S',       'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A4-BW-PRINT-2S',       'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A4-B/W-WHITE-ENVELOP', 'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.1200'),
    ('A4-COL-COPY-1S',       'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A4CLRC2',              'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A4-COL-PRINT-1S',      'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A4CLRP2',              'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A4-COLOR-WHITE-ENVEL', 'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.1200'),
    ('A4-FLYER',             'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A4-FLYER-2-SIDED',     'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A4-LAM',               'LAMINATE', 'LAMINATOR',     1, '1.00', '0.3500'),
    ('A4-SCAN',              'PRINT',    'DIGITAL_PRESS', 1, '1.50', '0.0400'),
    ('A4SC1',                'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.1200'),
    ('A4SC2',                'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.1200'),
    ('A5-BROWN-ENVELOPE',    'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.1200'),
    ('A5-FLYER',             'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('A5-FLYER-2SIDED',      'PRINT',    'DIGITAL_PRESS', 1, '2.00', '0.0500'),
    ('DL-ENVELOPE-PRINTING', 'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.1200'),
    ('FORMS-AND-FILING',     'FINISH',   None,            1, '0.00', '5.0000'),
    ('LOGO',                 'FINISH',   None,            1, '0.00', '5.0000'),
    ('PP-US',                'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.2500'),
    ('PP-US',                'CUT',      None,            2, '1.00', '0.2000'),
    ('PP-BR',                'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.2500'),
    ('PP-BR',                'CUT',      None,            2, '1.00', '0.2000'),
    ('PP-CA',                'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.2500'),
    ('PP-CA',                'CUT',      None,            2, '1.00', '0.2000'),
    ('PHOTO-PRINTING',       'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.2500'),
    ('PHOTO-PRINTING-(FULL', 'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.2500'),
    ('TYPING',               'FINISH',   None,            1, '0.00', '5.0000'),
    ('ZETA-PAPER-PRINTING',  'PRINT',    'DIGITAL_PRESS', 1, '3.00', '0.1200'),

    # ── Large format ──────────────────────────────────────────────
    #
    # The manufacturer's figures at the pass count each service runs:
    # 4 pass for flexy, which is read from across a road, and 6 pass
    # for SAV, which ends up on a window at arm's length. More passes
    # means more ink layers and proportionally slower.
    #
    #   E1902 (1900mm, i3200 2H)   4 pass 39 m²/h   6 pass 32 m²/h
    #   E3202 (3200mm, i3200 2H)   4 pass 30 m²/h   6 pass 24 m²/h
    #
    # 39 m²/h is 0.143 minutes per square foot; 32 is 0.174. Those
    # figures assume a machine that never pauses, which is what the
    # setup minutes carry.
    ('FLEXY',                'PRINT',    'LARGE_FORMAT',  1, '12.00', '0.1430'),
    # Hand-cut: a banner is wider than the plotter, and the time is
    # much the same whether it is six feet or sixteen.
    ('FLEXY',                'CUT',      None,            2, '10.00', '0.0000'),
    # Hemming and eyelets, which grow with the perimeter.
    ('FLEXY',                'FINISH',   None,            3, '5.00',  '0.2500'),

    ('SAV',                  'PRINT',    'LARGE_FORMAT',  1, '12.00', '0.1740'),
    # The plotter cuts at 1000mm/s, so the blade is seconds. This is
    # loading, registration and weeding.
    ('SAV',                  'CUT',      'PLOTTER',       2, '8.00',  '0.4000'),
]


class Command(BaseCommand):
    help = 'Seeds the production floor: stations, machine types, and service routes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--prune', action='store_true',
            help='Remove service routes not listed here. Off by default: a '
                 'route added on the floor and not yet written down would '
                 'be destroyed by a careless run.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.jobs.models import Service
        from apps.production.models import MachineType, ServiceStation, Station

        # ── Stations ──────────────────────────────────────────────────
        stations = {}
        for sequence, code, name in STATIONS:
            station, _ = Station.objects.update_or_create(
                code=code,
                defaults={'name': name, 'sequence': sequence, 'is_active': True},
            )
            stations[code] = station
        self.stdout.write(f'{len(stations)} stations')

        # ── Machine types ─────────────────────────────────────────────
        types = {}
        for code, name, station_code, paper in MACHINE_TYPES:
            machine_type, _ = MachineType.objects.update_or_create(
                code=code,
                defaults={
                    'name': name,
                    'station': stations[station_code],
                    'max_paper_size': paper,
                    'is_active': True,
                },
            )
            types[code] = machine_type
        self.stdout.write(f'{len(types)} machine types')

        # ── Routes ────────────────────────────────────────────────────
        seen = set()
        missing = []
        for code, station_code, type_code, sequence, setup, per_unit in ROUTES:
            service = Service.objects.filter(code=code).first()
            if service is None:
                missing.append(code)
                continue

            route, _ = ServiceStation.objects.update_or_create(
                service=service,
                station=stations[station_code],
                sequence=sequence,
                defaults={
                    'machine_type': types.get(type_code) if type_code else None,
                    'setup_minutes': Decimal(setup),
                    'minutes_per_unit': Decimal(per_unit),
                },
            )
            seen.add(route.pk)

        self.stdout.write(f'{len(seen)} service routes')

        if missing:
            self.stdout.write(self.style.WARNING(
                f'{len(missing)} service(s) in this file do not exist here: '
                f'{", ".join(sorted(set(missing)))}'
            ))

        if options['prune']:
            extra = ServiceStation.objects.exclude(pk__in=seen)
            count = extra.count()
            if count:
                for route in extra.select_related('service', 'station'):
                    self.stdout.write(self.style.WARNING(
                        f'  removing {route.service.code} -> {route.station.code}'
                    ))
                extra.delete()
            self.stdout.write(f'pruned {count} route(s) not listed here')

        self.stdout.write(self.style.SUCCESS('Floor seeded.'))