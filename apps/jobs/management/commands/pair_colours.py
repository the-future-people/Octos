"""
Pair each colour printing service with its black-and-white counterpart.

    python manage.py pair_colours          # shows the pairs it would make
    python manage.py pair_colours --apply  # makes them

A page set switched to black and white is priced as the matching
black-and-white service: same size, same sides, same kind of work
(printing or photocopy). Matched by name with "Color"/"Colour" swapped
for "B&W", so "A4 Color Printing 2-sided" pairs with "A4 B&W Printing
2-sided". Anything without an exact match is listed, never guessed.
"""

import re

from django.core.management.base import BaseCommand


def _key(name):
    n = name.lower().replace('colour', 'color')
    n = re.sub(r'\bcolor\b', '#', n)
    n = re.sub(r'\bb\s*&\s*w\b|\bblack\s*(&|and)\s*white\b', '#', n)
    return re.sub(r'\s+', ' ', n).strip()


class Command(BaseCommand):
    help = 'Pair colour services with their black-and-white counterparts.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **options):
        from apps.jobs.models import Service

        services = list(Service.objects.filter(is_active=True))
        colour = [s for s in services if re.search(r'colou?r', s.name, re.I)]
        mono = {}
        for s in services:
            if re.search(r'\bb\s*&\s*w\b|black\s*(&|and)\s*white', s.name, re.I):
                mono.setdefault(_key(s.name), s)

        paired = missing = 0
        for s in colour:
            match = mono.get(_key(s.name))
            if match is None:
                missing += 1
                self.stdout.write(f'  no black-and-white match: {s.code} · {s.name}')
                continue
            paired += 1
            self.stdout.write(f'  {s.code} · {s.name}  ->  {match.code} · {match.name}')
            if apply and s.bw_counterpart_id != match.pk:
                s.bw_counterpart = match
                s.save(update_fields=['bw_counterpart'])

        verb = 'Paired' if apply else 'Would pair'
        self.stdout.write(self.style.SUCCESS(f'{verb} {paired}; {missing} without a match.'))