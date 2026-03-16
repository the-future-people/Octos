"""
python manage.py seed_spec_templates

Seeds spec_template on the 5 existing services.
Safe to run multiple times — only updates if spec_template is empty.
"""
from django.core.management.base import BaseCommand


SPEC_TEMPLATES = {
    'Photocopy': [
        {
            'key': 'quantity', 'label': 'Quantity', 'type': 'number',
            'required': True, 'default': 1, 'min': 1,
        },
        {
            'key': 'pages', 'label': 'Pages per Copy', 'type': 'number',
            'required': True, 'default': 1, 'min': 1,
        },
        {
            'key': 'color', 'label': 'Color', 'type': 'select',
            'required': True, 'options': ['B&W', 'Color'], 'default': 'B&W',
        },
        {
            'key': 'sides', 'label': 'Sides', 'type': 'select',
            'required': True, 'options': ['Single-sided', 'Double-sided'], 'default': 'Single-sided',
        },
    ],

    'ID Card Printing': [
        {
            'key': 'quantity', 'label': 'Quantity', 'type': 'number',
            'required': True, 'default': 1, 'min': 1,
        },
        {
            'key': 'sides', 'label': 'Sides', 'type': 'select',
            'required': True, 'options': ['Single-sided', 'Double-sided'], 'default': 'Double-sided',
        },
    ],

    'Banner Printing': [
        {
            'key': 'width_ft', 'label': 'Width', 'type': 'number',
            'required': True, 'default': 4, 'min': 1, 'max': 100, 'unit': 'ft',
        },
        {
            'key': 'height_ft', 'label': 'Height', 'type': 'number',
            'required': True, 'default': 2, 'min': 1, 'max': 100, 'unit': 'ft',
        },
        {
            'key': 'material', 'label': 'Material', 'type': 'select',
            'required': True,
            'options': ['Vinyl', 'Canvas', 'Mesh', 'Backlit Film'],
            'default': 'Vinyl',
        },
        {
            'key': 'finishing', 'label': 'Finishing', 'type': 'select',
            'required': True,
            'options': ['Hemmed & Eyelets', 'Hemmed Only', 'No Finishing'],
            'default': 'Hemmed & Eyelets',
        },
        {
            'key': 'quantity', 'label': 'Quantity', 'type': 'number',
            'required': True, 'default': 1, 'min': 1,
        },
    ],

    'Business Cards': [
        {
            'key': 'quantity', 'label': 'Quantity', 'type': 'number',
            'required': True, 'default': 100, 'min': 50, 'unit': 'cards',
        },
        {
            'key': 'size', 'label': 'Card Size', 'type': 'select',
            'required': True,
            'options': ['Standard (85×54mm)', 'Square (55×55mm)', 'Mini (70×28mm)'],
            'default': 'Standard (85×54mm)',
        },
        {
            'key': 'paper_stock', 'label': 'Paper Stock', 'type': 'select',
            'required': True,
            'options': ['Matte 350gsm', 'Glossy 350gsm', 'Kraft', 'Soft Touch'],
            'default': 'Matte 350gsm',
        },
        {
            'key': 'sides', 'label': 'Sides', 'type': 'select',
            'required': True,
            'options': ['Single-sided', 'Double-sided'],
            'default': 'Double-sided',
        },
    ],

    'Logo Design': [
        {
            'key': 'style', 'label': 'Design Style', 'type': 'select',
            'required': True,
            'options': ['Modern', 'Minimalist', 'Classic', 'Playful', 'Bold'],
            'default': 'Modern',
        },
        {
            'key': 'color_preference', 'label': 'Color Preferences', 'type': 'text',
            'required': False,
            'default': 'e.g. Blue and gold, or no preference',
        },
        {
            'key': 'notes', 'label': 'Brief / Additional Notes', 'type': 'textarea',
            'required': False,
            'default': 'Describe what the logo is for, any references, or special requirements…',
        },
    ],
}


class Command(BaseCommand):
    help = 'Seeds spec_template on existing services'

    def handle(self, *args, **options):
        from apps.jobs.models import Service

        updated = 0
        skipped = 0

        for service_name, template in SPEC_TEMPLATES.items():
            try:
                service = Service.objects.get(name=service_name)
            except Service.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'  Service not found: {service_name}'))
                continue

            if service.spec_template:
                self.stdout.write(f'  Skipped (already set): {service_name}')
                skipped += 1
                continue

            service.spec_template = template
            service.save(update_fields=['spec_template'])
            self.stdout.write(self.style.SUCCESS(f'  ✓ {service_name} — {len(template)} fields'))
            updated += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. Updated: {updated}, Skipped: {skipped}'
        ))