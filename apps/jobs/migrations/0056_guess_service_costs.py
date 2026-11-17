"""
A first guess at what each printing service costs to make (17 Nov 2026),
from its name: colour, black and white or photocopy pages, and A3 as twice
A4. Everything else stays "not set" until someone gives it a cost. The
Branch Manager corrects any of it from the catalogue.
"""
from django.db import migrations

PAGE_WORDS = ('print', 'photocopy', 'copy')


def guess(apps, schema_editor):
    Service = apps.get_model('jobs', 'Service')
    for service in Service.objects.filter(cost_basis='NONE'):
        name = (service.name or '').lower()
        unit = (service.unit or '').upper().replace('PER_', '')
        if unit not in ('COPY', 'PAGE', 'SHEET') or not any(w in name for w in PAGE_WORDS):
            continue
        if 'colour' in name or 'color' in name:
            basis = 'COLOUR_PAGE'
        elif 'black' in name or 'b&w' in name or 'photocopy' in name:
            basis = 'BW_PAGE'
        else:
            continue
        service.cost_basis = basis
        service.cost_size = 2 if 'a3' in name else 1
        service.save(update_fields=['cost_basis', 'cost_size'])


class Migration(migrations.Migration):

    dependencies = [('jobs', '0055_discounts_and_costs')]

    operations = [migrations.RunPython(guess, migrations.RunPython.noop)]
