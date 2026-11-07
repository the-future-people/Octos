"""
Pages before copies in every product form that asks both (Khofi, 7 Nov 2026).

    python manage.py catalogue_pages_first           shows what would change, saves nothing
    python manage.py catalogue_pages_first --apply   makes the changes
"""
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = 'Pages before copies in product forms (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **options):
        from apps.jobs.models import Service
        changed = 0
        with transaction.atomic():
            for s in Service.objects.filter(is_active=True).order_by('code'):
                form = s.spec_template
                if not isinstance(form, list):
                    continue
                keys = [f.get('key') for f in form if isinstance(f, dict)]
                if 'pages' not in keys or 'quantity' not in keys or keys.index('pages') < keys.index('quantity'):
                    continue
                pages = [f for f in form if isinstance(f, dict) and f.get('key') == 'pages']
                rest = [f for f in form if not (isinstance(f, dict) and f.get('key') == 'pages')]
                at = next(i for i, f in enumerate(rest) if isinstance(f, dict) and f.get('key') == 'quantity')
                s.spec_template = rest[:at] + pages + rest[at:]
                s.save(update_fields=['spec_template'])
                changed += 1
                self.stdout.write(f"  {s.code}: {[f.get('key') for f in s.spec_template]}")
            if not changed:
                self.stdout.write('Nothing to change: pages already come first.')
            if apply:
                self.stdout.write(f'\nApplied: {changed} form(s).')
            else:
                transaction.set_rollback(True)
                self.stdout.write(f'\nDry run: {changed} form(s) would change, nothing saved. Run with --apply.')
