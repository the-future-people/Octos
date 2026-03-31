from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0011_monthlyclose'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashierfloat',
            name='morning_acknowledged',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='cashierfloat',
            name='morning_acknowledged_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='cashierfloat',
            name='opening_denomination_breakdown',
            field=models.JSONField(
                blank=True,
                null=True,
                help_text='Denomination count at float receipt — e.g. {"1":0,"2":0,"5":2,"10":0,"20":2,"50":0,"100":0,"200":0}',
            ),
        ),
        migrations.AddField(
            model_name='cashierfloat',
            name='closing_denomination_breakdown',
            field=models.JSONField(
                blank=True,
                null=True,
                help_text='Denomination count at EOD cash count — same structure as opening',
            ),
        ),
    ]