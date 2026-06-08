from django.db import migrations
import datetime


def update_shift_times(apps, schema_editor):
    BranchShift     = apps.get_model("hr", "BranchShift")
    ShiftRoleConfig = apps.get_model("hr", "ShiftRoleConfig")

    for shift in BranchShift.objects.all():
        shift.end_time = datetime.time(19, 30)
        shift.save(update_fields=["end_time"])

        ShiftRoleConfig.objects.filter(
            shift=shift, role_name="ATTENDANT"
        ).update(
            role_end_time    = datetime.time(19, 0),
            job_lock_buffer  = 0,
            signoff_buffer   = 50,
            autoclose_buffer = None,
        )

        ShiftRoleConfig.objects.filter(
            shift=shift, role_name="CASHIER"
        ).update(
            role_end_time    = datetime.time(19, 30),
            job_lock_buffer  = 0,
            signoff_buffer   = 60,
            autoclose_buffer = None,
        )

        ShiftRoleConfig.objects.filter(
            shift=shift, role_name="BRANCH_MANAGER"
        ).update(
            role_end_time    = datetime.time(19, 30),
            job_lock_buffer  = 0,
            signoff_buffer   = 150,
            autoclose_buffer = 150,
        )


def reverse_shift_times(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0006_merge_20260603_1826"),
    ]

    operations = [
        migrations.RunPython(update_shift_times, reverse_shift_times),
    ]
