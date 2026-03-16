from django.core.management.base import BaseCommand


# ─────────────────────────────────────────────────────────────────────────────
# Service definitions
# ─────────────────────────────────────────────────────────────────────────────

SERVICES = [

    # ── INSTANT ───────────────────────────────────────────────────────────────

    {
        'name'                : 'A4 B&W Photocopy 1-sided',
        'code'                : 'A4-BW-COPY-1S',
        'category'            : 'INSTANT',
        'unit'                : 'page',
        'description'         : 'Black and white photocopy on A4, single sided',
        'requires_design'     : False,
        'requires_file_upload': False,
        'base_price'          : 1.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Copies',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'pages', 'label': 'Pages per Copy',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A4 B&W Photocopy 2-sided',
        'code'                : 'A4-BW-COPY-2S',
        'category'            : 'INSTANT',
        'unit'                : 'page',
        'description'         : 'Black and white photocopy on A4, double sided',
        'requires_design'     : False,
        'requires_file_upload': False,
        'base_price'          : 1.50,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Copies',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'pages', 'label': 'Pages per Copy',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A4 Color Photocopy 1-sided',
        'code'                : 'A4-COL-COPY-1S',
        'category'            : 'INSTANT',
        'unit'                : 'page',
        'description'         : 'Full color photocopy on A4, single sided',
        'requires_design'     : False,
        'requires_file_upload': False,
        'base_price'          : 2.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Copies',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'pages', 'label': 'Pages per Copy',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A4 B&W Printing 1-sided',
        'code'                : 'A4-BW-PRINT-1S',
        'category'            : 'INSTANT',
        'unit'                : 'page',
        'description'         : 'Black and white print on A4, single sided',
        'requires_design'     : False,
        'requires_file_upload': True,
        'base_price'          : 1.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Copies',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'pages', 'label': 'Pages per Copy',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A4 B&W Printing 2-sided',
        'code'                : 'A4-BW-PRINT-2S',
        'category'            : 'INSTANT',
        'unit'                : 'page',
        'description'         : 'Black and white print on A4, double sided',
        'requires_design'     : False,
        'requires_file_upload': True,
        'base_price'          : 1.50,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Copies',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'pages', 'label': 'Pages per Copy',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A4 Color Printing 1-sided',
        'code'                : 'A4-COL-PRINT-1S',
        'category'            : 'INSTANT',
        'unit'                : 'page',
        'description'         : 'Full color print on A4, single sided',
        'requires_design'     : False,
        'requires_file_upload': True,
        'base_price'          : 2.50,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Copies',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'pages', 'label': 'Pages per Copy',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A3 B&W Photocopy',
        'code'                : 'A3-BW-COPY',
        'category'            : 'INSTANT',
        'unit'                : 'page',
        'description'         : 'Black and white photocopy on A3',
        'requires_design'     : False,
        'requires_file_upload': False,
        'base_price'          : 3.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Copies',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'pages', 'label': 'Pages per Copy',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A3 B&W Printing',
        'code'                : 'A3-BW-PRINT',
        'category'            : 'INSTANT',
        'unit'                : 'page',
        'description'         : 'Black and white print on A3',
        'requires_design'     : False,
        'requires_file_upload': True,
        'base_price'          : 3.50,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Copies',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'pages', 'label': 'Pages per Copy',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A3 Color Photocopy',
        'code'                : 'A3-COL-COPY',
        'category'            : 'INSTANT',
        'unit'                : 'page',
        'description'         : 'Full color photocopy on A3',
        'requires_design'     : False,
        'requires_file_upload': False,
        'base_price'          : 4.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Copies',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'pages', 'label': 'Pages per Copy',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A3 Color Printing',
        'code'                : 'A3-COL-PRINT',
        'category'            : 'INSTANT',
        'unit'                : 'page',
        'description'         : 'Full color print on A3',
        'requires_design'     : False,
        'requires_file_upload': True,
        'base_price'          : 5.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Copies',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'pages', 'label': 'Pages per Copy',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A3 B&W 2-sided Printing',
        'code'                : 'A3-BW-PRINT-2S',
        'category'            : 'INSTANT',
        'unit'                : 'page',
        'description'         : 'Black and white print on A3, double sided',
        'requires_design'     : False,
        'requires_file_upload': True,
        'base_price'          : 6.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Copies',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'pages', 'label': 'Pages per Copy',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'Typing',
        'code'                : 'TYPING',
        'category'            : 'INSTANT',
        'unit'                : 'page',
        'description'         : 'Document typing service — GHS 20/page up to 5 pages, GHS 15/page beyond',
        'requires_design'     : False,
        'requires_file_upload': False,
        'base_price'          : 20.00,  # fallback only — tiers take over
        'pricing_tiers'       : [
            {'min': 1, 'max': 5,    'price_per_unit': 20.00},
            {'min': 6, 'max': None, 'price_per_unit': 15.00},
        ],
        'spec_template'       : [
            {
                'key': 'pages', 'label': 'Number of Pages',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'Binding',
        'code'                : 'BINDING',
        'category'            : 'INSTANT',
        'unit'                : 'piece',
        'description'         : 'Document binding — GHS 10 (1-100pp), GHS 20 (101-200pp), GHS 40 (201+pp)',
        'requires_design'     : False,
        'requires_file_upload': False,
        'base_price'          : 10.00,  # fallback only — tiers take over
        'pricing_tiers'       : [
            {'min': 1,   'max': 100,  'flat_price': 10.00},
            {'min': 101, 'max': 200,  'flat_price': 20.00},
            {'min': 201, 'max': None, 'flat_price': 40.00},
        ],
        'spec_template'       : [
            {
                'key': 'pages', 'label': 'Number of Pages',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'binding_type', 'label': 'Binding Type',
                'type': 'select',
                'options': ['Spiral', 'Comb', 'Thermal', 'Hardcover'],
                'default': 'Spiral', 'required': True,
            },
            {
                'key': 'quantity', 'label': 'Number of Documents',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A4 Lamination',
        'code'                : 'A4-LAM',
        'category'            : 'INSTANT',
        'unit'                : 'sheet',
        'description'         : 'Lamination of A4 documents',
        'requires_design'     : False,
        'requires_file_upload': False,
        'base_price'          : 10.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Sheets',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A3 Lamination',
        'code'                : 'A3-LAM',
        'category'            : 'INSTANT',
        'unit'                : 'sheet',
        'description'         : 'Lamination of A3 documents',
        'requires_design'     : False,
        'requires_file_upload': False,
        'base_price'          : 20.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Sheets',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A4 Brown Envelope',
        'code'                : 'A4-ENV',
        'category'            : 'INSTANT',
        'unit'                : 'piece',
        'description'         : 'A4 brown envelope — sold individually',
        'requires_design'     : False,
        'requires_file_upload': False,
        'base_price'          : 2.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Quantity',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'A3 Brown Envelope',
        'code'                : 'A3-ENV',
        'category'            : 'INSTANT',
        'unit'                : 'piece',
        'description'         : 'A3 brown envelope — sold individually',
        'requires_design'     : False,
        'requires_file_upload': False,
        'base_price'          : 3.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Quantity',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    # ── PRODUCTION ────────────────────────────────────────────────────────────

    {
        'name'                : 'ID Card Printing',
        'code'                : 'ID-CARD',
        'category'            : 'PRODUCTION',
        'unit'                : 'piece',
        'description'         : 'ID card design and printing — requires production handoff',
        'requires_design'     : False,
        'requires_file_upload': True,
        'base_price'          : 15.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Number of Cards',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
            {
                'key': 'sides', 'label': 'Sides',
                'type': 'select',
                'options': ['Single-sided', 'Double-sided'],
                'default': 'Double-sided', 'required': True,
            },
        ],
    },

    {
        'name'                : 'Banner Printing',
        'code'                : 'BANNER',
        'category'            : 'PRODUCTION',
        'unit'                : 'piece',
        'description'         : 'Large format banner printing',
        'requires_design'     : False,
        'requires_file_upload': True,
        'base_price'          : 50.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'width_ft', 'label': 'Width (ft)',
                'type': 'number', 'min': 1, 'max': 100, 'default': 4, 'required': True,
            },
            {
                'key': 'height_ft', 'label': 'Height (ft)',
                'type': 'number', 'min': 1, 'max': 100, 'default': 2, 'required': True,
            },
            {
                'key': 'material', 'label': 'Material',
                'type': 'select',
                'options': ['Vinyl', 'Canvas', 'Mesh', 'Backlit Film'],
                'default': 'Vinyl', 'required': True,
            },
            {
                'key': 'finishing', 'label': 'Finishing',
                'type': 'select',
                'options': ['Hemmed & Eyelets', 'Hemmed Only', 'No Finishing'],
                'default': 'Hemmed & Eyelets', 'required': True,
            },
            {
                'key': 'quantity', 'label': 'Quantity',
                'type': 'number', 'min': 1, 'default': 1, 'required': True,
            },
        ],
    },

    {
        'name'                : 'Business Cards',
        'code'                : 'BIZ-CARDS',
        'category'            : 'PRODUCTION',
        'unit'                : 'piece',
        'description'         : 'Custom business card design and printing',
        'requires_design'     : False,
        'requires_file_upload': True,
        'base_price'          : 30.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'quantity', 'label': 'Quantity',
                'type': 'number', 'min': 50, 'default': 100, 'required': True,
                'unit': 'cards',
            },
            {
                'key': 'size', 'label': 'Card Size',
                'type': 'select',
                'options': ['Standard (85×54mm)', 'Square (55×55mm)', 'Mini (70×28mm)'],
                'default': 'Standard (85×54mm)', 'required': True,
            },
            {
                'key': 'paper_stock', 'label': 'Paper Stock',
                'type': 'select',
                'options': ['Matte 350gsm', 'Glossy 350gsm', 'Kraft', 'Soft Touch'],
                'default': 'Matte 350gsm', 'required': True,
            },
            {
                'key': 'sides', 'label': 'Sides',
                'type': 'select',
                'options': ['Single-sided', 'Double-sided'],
                'default': 'Double-sided', 'required': True,
            },
        ],
    },

    # ── DESIGN ────────────────────────────────────────────────────────────────

    {
        'name'                : 'Logo Design',
        'code'                : 'LOGO',
        'category'            : 'DESIGN',
        'unit'                : 'piece',
        'description'         : 'Custom logo design — brief required before payment',
        'requires_design'     : True,
        'requires_file_upload': False,
        'base_price'          : 150.00,
        'pricing_tiers'       : None,
        'spec_template'       : [
            {
                'key': 'style', 'label': 'Design Style',
                'type': 'select',
                'options': ['Modern', 'Minimalist', 'Classic', 'Playful', 'Bold'],
                'default': 'Modern', 'required': True,
            },
            {
                'key': 'color_preference', 'label': 'Color Preferences',
                'type': 'text',
                'default': 'e.g. Blue and gold, or no preference',
                'required': False,
            },
            {
                'key': 'notes', 'label': 'Brief / Additional Notes',
                'type': 'textarea',
                'default': 'Describe what the logo is for…',
                'required': False,
            },
        ],
    },
]


class Command(BaseCommand):
    help = 'Seed services and pricing rules for all active branches'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--wipe',
            action='store_true',
            help='Wipe existing services and pricing rules before seeding',
        )

    def handle(self, *args, **options) -> None:
        from apps.jobs.models import Service
        from apps.jobs.models import PricingRule
        from apps.organization.models import Branch
        from decimal import Decimal

        if options['wipe']:
            self.stdout.write('Wiping existing services and pricing rules...')
            PricingRule.objects.all().delete()
            Service.objects.all().delete()
            self.stdout.write(self.style.WARNING('  Wiped.'))

        branches = list(Branch.objects.filter(is_active=True))
        self.stdout.write(
            f'Seeding {len(SERVICES)} services across '
            f'{len(branches)} active branches...\n'
        )

        for svc_data in SERVICES:
            pricing_tiers = svc_data.pop('pricing_tiers')
            base_price    = svc_data.pop('base_price')

            service, created = Service.objects.update_or_create(
                code     = svc_data['code'],
                defaults = svc_data,
            )

            action = 'Created' if created else 'Updated'
            self.stdout.write(
                f'  {action}: [{service.category}] {service.name}'
            )

            # Seed pricing rule for each active branch
            for branch in branches:
                rule, rule_created = PricingRule.objects.update_or_create(
                    service = service,
                    branch  = branch,
                    defaults={
                        'base_price'    : Decimal(str(base_price)),
                        'pricing_tiers' : pricing_tiers,
                        'is_active'     : True,
                    },
                )
                rule_action = 'created' if rule_created else 'updated'
                self.stdout.write(
                    f'    └─ {branch.code}: GHS {base_price} [{rule_action}]'
                )

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {len(SERVICES)} services seeded across '
            f'{len(branches)} branches.'
        ))