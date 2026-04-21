import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_staff_assignment_pending_activation'),
        ('organization', '0003_branch_closing_time_branch_getfund_rate_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='pendingactivation',
            name='conflict_new_region',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='conflict_reassignments_region',
                to='organization.region',
            ),
        ),
    ]