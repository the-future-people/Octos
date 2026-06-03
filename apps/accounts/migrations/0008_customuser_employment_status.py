from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_role_constrained_scope'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='employment_status',
            field=models.CharField(
                choices=[
                    ('SHADOW',   'Shadow'),
                    ('ACTIVE',   'Active'),
                    ('INACTIVE', 'Inactive'),
                ],
                default='ACTIVE',
                help_text=(
                    'Operational state of the employee. '
                    'SHADOW = read-only pre-start access. '
                    'ACTIVE = full access. '
                    'INACTIVE = departed or suspended.'
                ),
                max_length=10,
            ),
        ),
    ]