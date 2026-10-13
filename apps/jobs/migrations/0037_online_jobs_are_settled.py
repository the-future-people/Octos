from django.db import migrations


def settle_online_jobs(apps, schema_editor):
    """
    Conversion wrote payment_state='PAID', which is not a value on the
    payment axis (UNPAID, DEPOSIT_PAID, SETTLED). choices are not
    enforced on create(), so it went in silently — and an attendant
    cannot release a job that is not SETTLED.

    0036 fixed the legacy status on these rows but matched on the bad
    value and left it in place. This corrects the value itself.
    Narrow on purpose, and safe to run twice.
    """
    Job = apps.get_model('jobs', 'Job')
    count = Job.objects.filter(
        intake_channel='ONLINE',
        payment_state='PAID',
    ).update(payment_state='SETTLED')
    print(f'  settled {count} online job(s)')


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0036_online_jobs_are_paid'),
    ]

    operations = [
        # No reverse: PAID was never a valid value to go back to.
        migrations.RunPython(settle_online_jobs, migrations.RunPython.noop),
    ]