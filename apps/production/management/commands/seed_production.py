"""
Seed stations and machine types, and register the machines a branch owns.

Idempotent, following the pattern in apps/core/management/commands/seed.py:
get_or_create for the vocabulary, so re-running adds what is missing
without disturbing what is there.

    python manage.py seed_production
    python manage.py seed_production --branch WLB
"""

from django.core.management.base import BaseCommand
from django.db import transaction


# Order matters: sequence is the order work flows through a branch.
STATIONS = [
    ('PRINT',    'Printing',        1),
    ('CUT',      'Cutting',         2),
    ('LAMINATE', 'Laminating',      3),
    ('BIND',     'Binding',         4),
    ('FINISH',   'Hand finishing',  5),
]

MACHINE_TYPES = [
    # code,            name,                    station,    max size
    ('DIGITAL_PRESS', 'Digital press',          'PRINT',    'A3'),
    ('LARGE_FORMAT',  'Large format printer',   'PRINT',    ''),
    ('PLOTTER',       'Plotter',                'PRINT',    ''),
    ('CUTTER',        'Cutter',                 'CUT',      'A3'),
    ('LAMINATOR',     'Laminator',              'LAMINATE', 'A3'),
    ('BINDER',        'Binding machine',        'BIND',     'A3'),
]

# What each branch actually owns. Only Westland is live.
BRANCH_MACHINES = {
    'WLB': [
        {
            'name':         'Canon C5535i',
            'model_number': 'imageRUNNER ADVANCE DX C5535i',
            'type':         'DIGITAL_PRESS',
        },
        {
            'name':         'Laminator',
            'model_number': '',
            'type':         'LAMINATOR',
        },
        {
            'name':         'Binding machine',
            'model_number': '',
            'type':         'BINDER',
        },
    ],
}


class Command(BaseCommand):
    help = 'Seed production stations, machine types and branch machines.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--branch',
            type=str,
            default=None,
            help='Only register machines for this branch code.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.organization.models import Branch
        from apps.production.models import Station, MachineType, Machine

        only_branch = options['branch']

        self.stdout.write('Seeding stations...')
        stations = {}
        for code, name, sequence in STATIONS:
            station, created = Station.objects.get_or_create(
                code=code,
                defaults={'name': name, 'sequence': sequence},
            )
            stations[code] = station
            self.stdout.write(
                f'  {"created" if created else "exists "}  {station.name}'
            )

        self.stdout.write('Seeding machine types...')
        types = {}
        for code, name, station_code, max_size in MACHINE_TYPES:
            mtype, created = MachineType.objects.get_or_create(
                code=code,
                defaults={
                    'name':           name,
                    'station':        stations[station_code],
                    'max_paper_size': max_size,
                },
            )
            types[code] = mtype
            self.stdout.write(
                f'  {"created" if created else "exists "}  {mtype.name}'
            )

        self.stdout.write('Registering machines...')
        registered = 0
        for branch_code, machines in BRANCH_MACHINES.items():
            if only_branch and branch_code != only_branch:
                continue

            branch = Branch.objects.filter(code=branch_code).first()
            if not branch:
                self.stdout.write(self.style.WARNING(
                    f'  branch {branch_code} not found — skipped'
                ))
                continue

            for spec in machines:
                # Matched on name within a branch: a branch does not have
                # two devices it calls the same thing, and serial numbers
                # are not always to hand when this is first run.
                machine, created = Machine.objects.get_or_create(
                    branch=branch,
                    name=spec['name'],
                    defaults={
                        'machine_type': types[spec['type']],
                        'model_number': spec['model_number'],
                    },
                )
                registered += 1 if created else 0
                self.stdout.write(
                    f'  {"created" if created else "exists "}  '
                    f'{branch_code} · {machine.name}'
                )

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {len(STATIONS)} stations, {len(MACHINE_TYPES)} machine '
            f'types, {registered} new machine(s).'
        ))