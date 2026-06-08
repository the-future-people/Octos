from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0016_add_intake_held_status'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='job',
            index=models.Index(fields=['branch', 'daily_sheet'], name='job_branch_sheet_idx'),
        ),
        migrations.AddIndex(
            model_name='job',
            index=models.Index(fields=['branch', 'status'], name='job_branch_status_idx'),
        ),
        migrations.AddIndex(
            model_name='job',
            index=models.Index(fields=['daily_sheet', 'status'], name='job_sheet_status_idx'),
        ),
        migrations.AddIndex(
            model_name='job',
            index=models.Index(fields=['branch', 'intake_by'], name='job_branch_intake_idx'),
        ),
        migrations.AddIndex(
            model_name='job',
            index=models.Index(fields=['branch', 'created_at'], name='job_branch_created_idx'),
        ),
        migrations.AddIndex(
            model_name='job',
            index=models.Index(fields=['daily_sheet', 'status', 'job_type'], name='job_sheet_status_type_idx'),
        ),
        migrations.AddIndex(
            model_name='job',
            index=models.Index(fields=['status'], name='job_status_idx'),
        ),
    ]
