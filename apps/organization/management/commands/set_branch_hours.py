"""
A branch's opening hours, weekdays and Saturday (7 Nov 2026).

    python manage.py set_branch_hours WLB --weekdays 07:30-19:30 --saturday 09:00-17:30
    python manage.py set_branch_hours WLB --weekdays 07:30-19:30 --saturday 09:00-17:30 --apply

Without --apply it only shows what would change. --saturday same clears
Saturday's own hours (Saturday then follows the weekdays).
"""
from datetime import time

from django.core.management.base import BaseCommand, CommandError


def _span(text):
    try:
        a, b = text.split('-')
        opens = time(*map(int, a.split(':')))
        closes = time(*map(int, b.split(':')))
    except Exception:
        raise CommandError(f'{text!r}: give hours as HH:MM-HH:MM, e.g. 07:30-19:30')
    if opens >= closes:
        raise CommandError(f'{text!r}: opening must be before closing')
    return opens, closes


class Command(BaseCommand):
    help = "Set a branch's weekday and Saturday hours."

    def add_arguments(self, parser):
        parser.add_argument('branch', help='The branch code, e.g. WLB')
        parser.add_argument('--weekdays', required=True, help='HH:MM-HH:MM, Monday to Friday')
        parser.add_argument('--saturday', help="HH:MM-HH:MM, or 'same' for the weekday hours")
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, branch, weekdays, saturday=None, apply=False, **options):
        from apps.organization.models import Branch
        b = Branch.objects.filter(code=branch).first()
        if b is None:
            raise CommandError(f'No branch with the code {branch!r}.')
        opens, closes = _span(weekdays)
        sat = (None, None) if (saturday or 'same') == 'same' else _span(saturday)

        def words(o, c):
            return f'{o:%H:%M} to {c:%H:%M}' if o and c else 'as weekdays'
        self.stdout.write(f'{b.name}:')
        self.stdout.write(f'  weekdays  {words(b.opening_time, b.closing_time)}  ->  {words(opens, closes)}')
        self.stdout.write(f'  Saturday  {words(b.saturday_opening_time, b.saturday_closing_time)}  ->  {words(*sat)}')
        if not apply:
            self.stdout.write('Nothing changed: add --apply to save.')
            return
        b.opening_time, b.closing_time = opens, closes
        b.saturday_opening_time, b.saturday_closing_time = sat
        b.save(update_fields=['opening_time', 'closing_time', 'saturday_opening_time', 'saturday_closing_time'])
        self.stdout.write('Saved.')
