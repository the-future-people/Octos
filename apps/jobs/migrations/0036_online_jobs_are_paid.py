from django.db import migrations


def mark_online_jobs_paid(apps, schema_editor):
    """
    Online jobs converted before the fix were born PENDING_PAYMENT.
    The money was already in, but the cashier queue, sheet close, EOD
    and monthly close all read the legacy status and saw a debt.

    Put them where a cashier would have left them once paid. Narrow on
    purpose: only online, only already paid on the payment axis, only
    still sitting at PENDING_PAYMENT. Safe to run twice.
    """
    Job = apps.get_model('jobs', 'Job')
    count = Job.objects.filter(
        intake_channel='ONLINE',
        payment_state='PAID',
        status='PENDING_PAYMENT',
    ).update(status='PAID', job_type='PRODUCTION')
    print(f'  marked {count} online job(s) paid')


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0035_alter_job_intake_channel'),
    ]

    operations = [
        # No reverse: there is no honest way to put a debt back.
        migrations.RunPython(mark_online_jobs_paid, migrations.RunPython.noop),
    ]