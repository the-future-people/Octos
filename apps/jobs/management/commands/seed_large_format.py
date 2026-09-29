"""
python manage.py seed_large_format

The first production services that are actually priced correctly.

Banner Printing was a placeholder: PER_PIECE at a flat GHS 50 whatever
the size, with six pricing rules across branches that do not trade. It
was never used on a single job. It is removed here rather than
deactivated — nothing references it, and a wrong price left in the
catalogue is a wrong price someone will eventually quote.

Flexy and SAV are priced (width" × height") ÷ 144 × rate, with a floor
of GHS 10 per piece: a small banner costs the same in file prep, cutting
and packing as a large one.

Only Westland is seeded. It is the only branch trading.

Safe to run repeatedly.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction


BRANCH_CODE = 'WLB'

# Width, height and quantity. Nothing else: what the customer is getting
# is confirmed on its own step, not inferred from a material dropdown.
LARGE_FORMAT_SPEC = [
    {
        'key': 'width_in', 'label': 'Width', 'type': 'number',
        'required': True, 'default': 72, 'min': 6, 'max': 600, 'unit': 'in',
    },
    {
        'key': 'height_in', 'label': 'Height', 'type': 'number',
        'required': True, 'default': 36, 'min': 6, 'max': 600, 'unit': 'in',
    },
    {
        'key': 'quantity', 'label': 'Quantity', 'type': 'number',
        'required': True, 'default': 1, 'min': 1,
    },
]

SERVICES = [
    {
        'code'        : 'FLEXY',
        'name'        : 'Flexy Banner',
        'description' : 'Outdoor flex banner, printed to size. Events, '
                        'shopfronts, church programmes.',
        'rate'        : Decimal('3.25'),
        'minimum'     : Decimal('10.00'),
    },
    {
        'code'        : 'SAV',
        'name'        : 'SAV Sticker',
        'description' : 'Self-adhesive vinyl, printed to size. Window '
                        'graphics, vehicle panels, large labels.',
        'rate'        : Decimal('2.80'),
        'minimum'     : Decimal('10.00'),
    },
]

RETIRE_CODES = ['BANNER']


class Command(BaseCommand):
    help = 'Seeds the large-format production services and retires the placeholder banner'

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.jobs.models import Service, PricingRule, JobLineItem
        from apps.organization.models import Branch

        try:
            branch = Branch.objects.get(code=BRANCH_CODE)
        except Branch.DoesNotExist:
            self.stderr.write(
                self.style.ERROR(f'Branch {BRANCH_CODE} not found — nothing seeded.')
            )
            return

        # ── Retire the placeholder ────────────────────────────────────
        for code in RETIRE_CODES:
            service = Service.objects.filter(code=code).first()
            if not service:
                continue

            used = JobLineItem.objects.filter(service=service).count()
            if used:
                self.stdout.write(self.style.WARNING(
                    f'{code} is on {used} line item(s) — deactivating instead '
                    f'of deleting, so the history still reads.'
                ))
                service.is_active = False
                service.save(update_fields=['is_active'])
                continue

            rules = PricingRule.objects.filter(service=service).count()
            PricingRule.objects.filter(service=service).delete()
            service.delete()
            self.stdout.write(
                f'Removed {code} and {rules} pricing rule(s) — never used on a job.'
            )

        # ── Seed the real ones ────────────────────────────────────────
        for spec in SERVICES:
            service, created = Service.objects.update_or_create(
                code=spec['code'],
                defaults={
                    'name'                : spec['name'],
                    'category'            : 'PRODUCTION',
                    'unit'                : 'PER_SQFT',
                    'description'         : spec['description'],
                    'requires_design'     : False,
                    'requires_file_upload': True,
                    'is_active'           : True,
                    'spec_template'       : LARGE_FORMAT_SPEC,
                },
            )

            rule, rule_created = PricingRule.objects.update_or_create(
                service=service, branch=branch,
                defaults={
                    'base_price'      : spec['rate'],
                    'color_multiplier': Decimal('1.00'),
                    'minimum_price'   : spec['minimum'],
                    'is_active'       : True,
                },
            )

            self.stdout.write(self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} {service.name} "
                f"— GHS {spec['rate']}/sq ft, minimum GHS {spec['minimum']} "
                f"at {branch.code}"
            ))

        self.stdout.write(self.style.SUCCESS('Large-format seeding complete.'))