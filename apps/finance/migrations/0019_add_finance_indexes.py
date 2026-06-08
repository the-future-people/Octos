from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0018_cashierfloat_is_overtime'),
    ]

    operations = [
        # DailySalesSheet indexes
        migrations.AddIndex(
            model_name='dailysalessheet',
            index=models.Index(fields=['branch', 'date'], name='sheet_branch_date_idx'),
        ),
        migrations.AddIndex(
            model_name='dailysalessheet',
            index=models.Index(fields=['branch', 'status'], name='sheet_branch_status_idx'),
        ),
        migrations.AddIndex(
            model_name='dailysalessheet',
            index=models.Index(fields=['status'], name='sheet_status_idx'),
        ),
        # Receipt indexes
        migrations.AddIndex(
            model_name='receipt',
            index=models.Index(fields=['daily_sheet', 'is_void'], name='receipt_sheet_void_idx'),
        ),
        migrations.AddIndex(
            model_name='receipt',
            index=models.Index(fields=['cashier', 'daily_sheet'], name='receipt_cashier_sheet_idx'),
        ),
        migrations.AddIndex(
            model_name='receipt',
            index=models.Index(fields=['daily_sheet', 'payment_method'], name='receipt_sheet_method_idx'),
        ),
        migrations.AddIndex(
            model_name='receipt',
            index=models.Index(fields=['created_at'], name='receipt_created_idx'),
        ),
    ]
