from django.db import migrations


def westland_trades(apps, schema_editor):
    # Only Westland trades on Octos today (Nov 2026). Set by name, so this
    # does nothing on a database without a Westland branch (tests, local).
    Branch = apps.get_model('organization', 'Branch')
    Branch.objects.filter(name='Westland Branch').update(is_trading=True)


class Migration(migrations.Migration):

    dependencies = [
        ('organization', '0005_branch_is_trading'),
    ]

    operations = [
        migrations.RunPython(westland_trades, migrations.RunPython.noop),
    ]