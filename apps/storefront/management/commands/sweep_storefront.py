"""
python manage.py sweep_storefront

Removes expired carts and the artwork waiting on nothing. Scheduled
nightly, and safe to run by hand at any time — a second run finds
nothing left to do.
"""

from django.core.management.base import BaseCommand

from apps.storefront.services.sweep import sweep


class Command(BaseCommand):
    help = 'Removes expired carts and staged uploads nobody committed'

    def handle(self, *args, **options):
        result = sweep()
        self.stdout.write(self.style.SUCCESS(
            f"Swept {result['orders']} order(s) and "
            f"{result['staged']} staged upload(s)."
        ))