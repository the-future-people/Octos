from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_customuser_region'),
    ]

    operations = [
        migrations.AddField(
            model_name='role',
            name='is_constrained',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'If True, only one MAIN and one DEPUTY may hold this '
                    'role per organisational unit simultaneously.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='role',
            name='scope',
            field=models.CharField(
                choices=[
                    ('BRANCH', 'Branch'),
                    ('REGION', 'Region'),
                    ('BELT',   'Belt'),
                    ('HQ',     'HQ'),
                ],
                default='BRANCH',
                help_text='Which organisational unit this role operates within.',
                max_length=10,
            ),
        ),
    ]