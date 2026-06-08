from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0019_add_finance_indexes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cashierfloat',
            name='daily_sheet',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=models.deletion.PROTECT,
                related_name='cashier_floats',
                to='finance.dailysalessheet',
                help_text='Null when staged — linked when sheet opens',
            ),
        ),
        migrations.AddIndex(
            model_name='cashierfloat',
            index=models.Index(
                fields=['physical_confirm_disputed', 'morning_acknowledged'],
                name='float_dispute_ack_idx',
            ),
        ),
        migrations.RenameIndex(
            model_name='cashierfloat',
            old_fields=['daily_sheet', 'cashier'],
            new_name='float_sheet_cashier_idx',
        ),
        migrations.RenameIndex(
            model_name='cashierfloat',
            old_fields=['scheduled_date', 'cashier'],
            new_name='float_scheduled_cashier_idx',
        ),
        migrations.RenameIndex(
            model_name='cashierfloat',
            old_fields=['is_signed_off'],
            new_name='float_signed_off_idx',
        ),
        migrations.RenameIndex(
            model_name='cashierfloat',
            old_fields=['morning_acknowledged'],
            new_name='float_morning_ack_idx',
        ),
    ]
