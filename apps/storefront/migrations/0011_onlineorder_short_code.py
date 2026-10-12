"""
A short code on every order, including the ones already here.

Added in three steps rather than one. A unique column with a blank
default cannot be added to a table that already has rows — they would
all share the same empty value, and Postgres refuses to build the
index. So the column arrives without the constraint, every existing
order is given a code, and only then is uniqueness enforced.
"""

from secrets import choice

from django.db import migrations, models

ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def give_everyone_a_code(apps, schema_editor):
    OnlineOrder = apps.get_model('storefront', 'OnlineOrder')

    taken = set(
        OnlineOrder.objects.exclude(short_code='')
        .values_list('short_code', flat=True)
    )

    for order in OnlineOrder.objects.filter(short_code=''):
        while True:
            code = ''.join(choice(ALPHABET) for _ in range(8))
            if code not in taken:
                taken.add(code)
                break
        OnlineOrder.objects.filter(pk=order.pk).update(short_code=code)


def take_them_away(apps, schema_editor):
    """Reversing this empties the column rather than dropping it."""
    OnlineOrder = apps.get_model('storefront', 'OnlineOrder')
    OnlineOrder.objects.update(short_code='')


class Migration(migrations.Migration):

    dependencies = [
        ('storefront', '0010_alter_onlineorder_job'),
    ]

    operations = [
        migrations.AddField(
            model_name='onlineorder',
            name='short_code',
            # No index yet. Unique brings its own in the third step, and
            # asking for one here means Postgres is told to create the
            # same index twice.
            field=models.CharField(
                max_length=8, blank=True, default='',
            ),
        ),
        migrations.RunPython(give_everyone_a_code, take_them_away),
        migrations.AlterField(
            model_name='onlineorder',
            name='short_code',
            field=models.CharField(
                max_length=8, unique=True, editable=False, db_index=True,
                default='', blank=True,
                help_text=(
                    'A second key to the same door, short enough to text. '
                    'The access token runs to 43 characters and a tracking '
                    'link carrying it leaves no room for a message around '
                    'it — an SMS has 160 before it splits in two and costs '
                    'double.'
                ),
            ),
        ),
    ]