from django.core.management.base import BaseCommand
from decimal import Decimal


class Command(BaseCommand):
    help = 'Seed inventory opening balances for Westland Branch'

    def handle(self, *args, **options):
        from apps.inventory.models import ConsumableCategory, ConsumableItem
        from apps.inventory.inventory_engine import InventoryEngine
        from apps.organization.models import Branch
        from apps.accounts.models import CustomUser

        branch = Branch.objects.get(code='WLB')
        actor  = CustomUser.objects.filter(branch=branch).first()
        engine = InventoryEngine(branch)

        self.stdout.write(f"Seeding inventory for: {branch.name}")

        cat_paper, _      = ConsumableCategory.objects.get_or_create(name='Paper')
        cat_envelope, _   = ConsumableCategory.objects.get_or_create(name='Envelopes')
        cat_binding, _    = ConsumableCategory.objects.get_or_create(name='Binding')
        cat_lamination, _ = ConsumableCategory.objects.get_or_create(name='Lamination')
        cat_toner, _      = ConsumableCategory.objects.get_or_create(name='Toner')

        items = [
            (cat_paper,      'A4 Paper 80gsm',            'A4',  'SHEETS',  'sheets', 250, 500, Decimal('625')),
            (cat_paper,      'A3 Paper 80gsm',            'A3',  'SHEETS',  'sheets', 100, 250, Decimal('125')),
            (cat_paper,      'A4 Art Paper Glossy',       'A4',  'SHEETS',  'sheets',  50, 250, Decimal('47')),
            (cat_paper,      'A3 Art Paper Glossy',       'A3',  'SHEETS',  'sheets', 100, 250, Decimal('328')),
            (cat_paper,      'A5 Art Paper Glossy',       'A5',  'SHEETS',  'sheets',  25, 100, Decimal('11')),
            (cat_paper,      'A4 Certificate Paper',      'A4',  'SHEETS',  'sheets',  20, 100, Decimal('43')),
            (cat_paper,      'A4 Shiny Card',             'A4',  'SHEETS',  'pcs',     20,  50, Decimal('50')),
            (cat_envelope,   'A4 Brown Envelope',         'A4',  'UNITS',   'pcs',    100, 250, Decimal('375')),
            (cat_binding,    'Binding Rings 8mm',         'N/A', 'UNITS',   'pcs',     20, 100, Decimal('50')),
            (cat_binding,    'Binding Rings 10mm',        'N/A', 'UNITS',   'pcs',     20, 100, Decimal('50')),
            (cat_binding,    'Binding Rings 12mm',        'N/A', 'UNITS',   'pcs',     20, 100, Decimal('50')),
            (cat_binding,    'Binding Rings 18mm',        'N/A', 'UNITS',   'pcs',     20, 100, Decimal('50')),
            (cat_lamination, 'A4 Lamination Pouches',     'A4',  'UNITS',   'pcs',     20, 100, Decimal('75')),
            (cat_lamination, 'A3 Lamination Pouches',     'A3',  'UNITS',   'pcs',     50, 250, Decimal('250')),
            (cat_toner,      'Canon 5535i Toner Black',   'N/A', 'PERCENT', '%',       15, 100, Decimal('60')),
            (cat_toner,      'Canon 5535i Toner Cyan',    'N/A', 'PERCENT', '%',       15, 100, Decimal('40')),
            (cat_toner,      'Canon 5535i Toner Magenta', 'N/A', 'PERCENT', '%',       15, 100, Decimal('40')),
            (cat_toner,      'Canon 5535i Toner Yellow',  'N/A', 'PERCENT', '%',       15, 100, Decimal('40')),
        ]

        created = 0
        for cat, name, size, unit_type, unit_label, rp, rq, opening in items:
            item, made = ConsumableItem.objects.get_or_create(
                category=cat, name=name,
                defaults=dict(paper_size=size, unit_type=unit_type,
                              unit_label=unit_label, reorder_point=rp, reorder_qty=rq)
            )
            if made:
                engine.set_opening_balance(item, opening, actor, 'Opening balance - Octos go-live')
                self.stdout.write(f"  Created: {name} = {opening} {unit_label}")
                created += 1
            else:
                self.stdout.write(f"  Exists:  {name}")

        self.stdout.write(self.style.SUCCESS(f"Done - {created} items created"))
