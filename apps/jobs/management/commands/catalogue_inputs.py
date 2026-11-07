"""
What each product asks for (Khofi, 7 Nov 2026).

    python manage.py catalogue_inputs           shows what would change, saves nothing
    python manage.py catalogue_inputs --apply   makes the changes, all or nothing
"""
from django.core.management.base import BaseCommand
from django.db import transaction

RINGS = [8, 10, 12, 14, 16, 19, 22, 25, 28, 32, 38, 45, 51]
BINDING = [
    {'key': 'ring_size', 'type': 'select', 'label': 'Ring size (mm)', 'options': RINGS, 'default': 8, 'required': True},
    {'key': 'binding_type', 'type': 'select', 'label': 'Binding type', 'default': 'Spiral',
     'options': ['Spiral', 'Comb', 'Thermal', 'Hardcover'], 'required': True},
    {'key': 'quantity', 'min': 1, 'type': 'number', 'label': 'Number of sets', 'default': 1, 'required': True},
]
SCANNING = [{'key': 'pages', 'min': 1, 'type': 'number', 'label': 'Number of pages', 'default': 1, 'required': True}]
FLYERS = [{'key': 'quantity', 'min': 10, 'type': 'number', 'label': 'Quantity', 'default': 10, 'required': True}]
PRINTING = [
    {'key': 'quantity', 'min': 1, 'type': 'number', 'label': 'Number of copies', 'default': 1, 'required': True},
    {'key': 'pages', 'min': 1, 'type': 'number', 'label': 'Pages per copy', 'default': 1, 'required': True},
]
FORMS = {
    'A4-BIND': BINDING, 'A3-BIND': BINDING,
    'A4-SCAN': SCANNING, 'A3-SCAN': SCANNING,
    'A4-FLYER': FLYERS, 'A4-FLYER-2-SIDED': FLYERS, 'A5-FLYER': FLYERS, 'A5-FLYER-2SIDED': FLYERS,
    # Both-sides products that had no form: pages and copies, like the rest.
    'A4CLRP2': PRINTING, 'A3CLRP2': PRINTING, 'A3BWP2': PRINTING,
    'A4CLRC2': PRINTING, 'A3CLRC2': PRINTING, 'A3BWC2': PRINTING,
}
TYPING_TIERS = [
    {'min': 1, 'max': 9, 'price_per_unit': 20.0},      # under 10 pages: GHS 20 a page
    {'min': 10, 'max': None, 'price_per_unit': 10.0},  # 10 pages or more: every page GHS 10
]


class Command(BaseCommand):
    help = 'What each product asks for (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Save the changes.')

    def handle(self, *args, apply=False, **options):
        from apps.jobs.models import PricingRule, Service
        changes = 0
        with transaction.atomic():
            for code, form in FORMS.items():
                s = Service.objects.filter(code=code).first()
                if s is None:
                    self.stdout.write(f'  {code}: not in this catalogue, skipped')
                elif s.spec_template != form:
                    s.spec_template = form
                    s.save(update_fields=['spec_template'])
                    changes += 1
                    self.stdout.write(f"  {code}: asks for {[f['key'] for f in form]}")
            rule = PricingRule.objects.filter(service__code='TYPING', is_active=True).first()
            if rule and rule.pricing_tiers != TYPING_TIERS:
                rule.pricing_tiers = TYPING_TIERS
                rule.save(update_fields=['pricing_tiers'])
                changes += 1
                self.stdout.write('  TYPING: GHS 20 a page under 10 pages, GHS 10 every page from 10')
            if not changes:
                self.stdout.write('Nothing to change: every product asks for what was decided.')
            if apply:
                self.stdout.write(f'\nApplied {changes} change(s).')
            else:
                transaction.set_rollback(True)
                self.stdout.write(f'\nDry run: {changes} change(s) shown, nothing saved. Run with --apply.')
