"""
The catalogue tidy of 7 Nov 2026, decided with Khofi.

    python manage.py catalogue_7nov           shows what would change, saves nothing
    python manage.py catalogue_7nov --apply   makes the changes, all or nothing

Safe to run twice: what is already right is left alone. Services are
switched off, never deleted, so old orders and invoices keep them.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

OFF = [
    ('CLEAR-BAG', 'not sold yet'),
    ('PHOTO-PRINTING-(FULL', 'a duplicate of Photo Printing'),
    ('A4-B/W-WHITE-ENVELOP', 'retired'),
    ('A4-COLOR-WHITE-ENVEL', 'retired'),
]
DEFAULTS = [
    ('A4-FLYER-2-SIDED', {'sides': 'DOUBLE'}),
    ('A5-FLYER-2SIDED', {'sides': 'DOUBLE'}),
    ('A3-ART-PAPER-2-SIDED', {'sides': 'DOUBLE'}),
    ('BIZ-CARDS', {'paper_size': 'NA'}),
    ('ID-CARD', {'paper_size': 'NA'}),
]
VERSIONS = [  # both-sides version -> its one-side product
    ('A4-BW-COPY-2S', 'A4-BW-COPY-1S'),
    ('A4CLRC2', 'A4-COL-COPY-1S'),
    ('A3BWC2', 'A3-BW-COPY'),
    ('A3CLRC2', 'A3-COL-COPY'),
    ('A3BWP2', 'A3-BW-PRINT'),
]
ROUTES = [  # no route yet -> made the same way as
    ('A3-ART-PAPER-2-SIDED', 'A3-ART-CARD-1-SIDED'),
    ('A3-LAMINATION---C.F-', 'A3-LAM'),
]
PRICES = [('A3-LAMINATION---C.F-', Decimal('10.00'))]
A3_PACKED_ON = ['A3-COL-PRINT', 'A3CLRP2', 'A3-BW-PRINT', 'A3BWP2']
WORDS = [
    ('PP-BR', 'Passport Photo (Regular / British)',
     'A set of 8 printed passport photos in the regular size (35 x 45 mm), also the British size. '
     'Priced per set: one set is 8 photos. Digital copies are done at the front desk only.'),
    ('ZETA-PAPER-PRINTING', None,
     'Printing on A4 Zeta paper: a textured, higher-quality paper, mostly used for letterheads.'),
    ('A3-LAMINATION---C.F-', None,
     "A3 lamination with the customer's own pouch (they bring it). Done at the front desk."),
]


class Command(BaseCommand):
    help = 'The catalogue tidy of 7 Nov 2026 (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Save the changes.')

    def handle(self, *args, apply=False, **options):
        self.changes = []
        with transaction.atomic():
            self.tidy()
            for line in self.changes:
                self.stdout.write(f'  {line}')
            if not self.changes:
                self.stdout.write('Nothing to change: the catalogue is already as decided.')
            if apply:
                self.stdout.write(f'\nApplied {len(self.changes)} change(s).')
            else:
                transaction.set_rollback(True)
                self.stdout.write(f'\nDry run: {len(self.changes)} change(s) shown, nothing saved. '
                                  f'Run with --apply to make them.')

    def note(self, text):
        self.changes.append(text)

    def tidy(self):
        from apps.jobs.models import PricingRule, Service
        from apps.production.models import ServiceStation

        def get(code):
            return Service.objects.filter(code=code).first()

        for code, why in OFF:
            s = get(code)
            if s and s.is_active:
                s.is_active = False
                s.save(update_fields=['is_active'])
                self.note(f'{code}: switched off ({why})')

        for code, wanted in DEFAULTS:
            s = get(code)
            if s is None:
                continue
            current = dict(s.smart_defaults or {})
            todo = {k: v for k, v in wanted.items() if current.get(k) != v}
            if todo:
                current.update(todo)
                s.smart_defaults = current
                s.save(update_fields=['smart_defaults'])
                self.note(f'{code}: defaults {todo}')

        for code, base_code in VERSIONS:
            s, base = get(code), get(base_code)
            if s and base and s.variant_of_id != base.pk:
                s.variant_of = base
                s.variant_label = s.variant_label or 'Both sides'
                s.save(update_fields=['variant_of', 'variant_label'])
                self.note(f'{code}: now the both-sides version of {base_code}')

        for code, price in PRICES:
            rule = PricingRule.objects.filter(service__code=code, is_active=True).first()
            if rule and rule.base_price != price:
                old = rule.base_price
                rule.base_price = price
                rule.save(update_fields=['base_price'])
                self.note(f'{code}: price GHS {old} -> GHS {price}')

        for code, like_code in ROUTES:
            s, like = get(code), get(like_code)
            if s is None or like is None or ServiceStation.objects.filter(service=s).exists():
                continue
            steps = list(ServiceStation.objects.filter(service=like))
            for step in steps:
                step.pk = None
                step.id = None
                step.service = s
                step.save()
            if steps:
                self.note(f'{code}: routed like {like_code} ({len(steps)} step(s))')

        pack = get('ENV-PACK-A3') or self._a3_packing(get('ENV-PACK-A4'), PricingRule, ServiceStation)
        if pack is not None:
            for code in A3_PACKED_ON:
                s = get(code)
                if s and not s.addons.filter(pk=pack.pk).exists():
                    s.addons.add(pack)
                    self.note(f'{code}: offers {pack.name}')

        for code, name, description in WORDS:
            s = get(code)
            if s is None:
                continue
            fields = []
            if name and s.name != name:
                s.name = name
                fields.append('name')
                if s.display_name:
                    s.display_name = name
                    fields.append('display_name')
            if description and s.description != description:
                s.description = description
                fields.append('description')
            if fields:
                s.save(update_fields=fields)
                self.note(f'{code}: {", ".join(fields)} updated')

    def _a3_packing(self, a4, PricingRule, ServiceStation):
        """A3 Brown Envelope (packed): the A4 one's copy, at GHS 3.00 (A3 envelopes' price)."""
        if a4 is None:
            self.note('ENV-PACK-A4 not found, so the A3 packing envelope was not created')
            return None
        branches = list(a4.branches.all())
        steps = list(ServiceStation.objects.filter(service=a4))
        rules = list(PricingRule.objects.filter(service=a4))
        pack = a4
        pack.pk = None
        pack.id = None
        pack.code = 'ENV-PACK-A3'
        pack.name = 'A3 Brown Envelope (packed)'
        if pack.display_name:
            pack.display_name = 'A3 Brown Envelope'
        pack.description = ('An A3 brown envelope to pack the order in: one for all copies '
                            'unless the customer asks for one each.')
        pack.save()
        pack.branches.set(branches)
        for step in steps:
            step.pk = None
            step.id = None
            step.service = pack
            step.save()
        for rule in rules:
            rule.pk = None
            rule.id = None
            rule.service = pack
            rule.base_price = Decimal('3.00')
            rule.save()
        self.note('ENV-PACK-A3: created, A3 Brown Envelope (packed), GHS 3.00')
        return pack
