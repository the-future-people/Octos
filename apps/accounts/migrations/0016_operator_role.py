"""
The Operator role: a person whose work is running machines.

The role decides where they land after sign-in (/operator) and keeps them
out of the counter and the money. What they may do at a machine is still
decided by their MachineOperator assignment, not by this role.
"""

from django.db import migrations


def add_operator(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    Role.objects.get_or_create(
        name='OPERATOR',
        defaults={
            'display_name':   'Operator',
            'is_constrained': False,
            'scope':          'BRANCH',
        },
    )


def remove_operator(apps, schema_editor):
    # Only if nobody holds it: never strand a person without a role.
    Role = apps.get_model('accounts', 'Role')
    CustomUser = apps.get_model('accounts', 'CustomUser')
    role = Role.objects.filter(name='OPERATOR').first()
    if role and not CustomUser.objects.filter(role=role).exists():
        role.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0015_drop_operator_pin'),
    ]

    operations = [
        migrations.RunPython(add_operator, remove_operator),
    ]