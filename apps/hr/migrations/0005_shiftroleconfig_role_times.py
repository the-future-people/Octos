from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0004_add_branch_shift_role_config'),
    ]

    operations = [
        migrations.AddField(
            model_name='shiftroleconfig',
            name='role_start_time',
            field=models.TimeField(
                null=True,
                blank=True,
                help_text=(
                    'Role-specific shift start time. '
                    'Overrides BranchShift.start_time when set. '
                    'Leave blank to inherit from parent shift.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='shiftroleconfig',
            name='role_end_time',
            field=models.TimeField(
                null=True,
                blank=True,
                help_text=(
                    'Role-specific shift end time. '
                    'Overrides BranchShift.end_time when set. '
                    'Leave blank to inherit from parent shift.'
                ),
            ),
        ),
    ]