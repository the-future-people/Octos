from django.db import migrations


def backfill(apps, schema_editor):
    """
    Map every existing job onto the three lifecycle axes.

    Without this the new fields default to UNPAID / RECEIVED /
    AWAITING_COLLECTION, which would claim that several thousand completed
    and paid jobs are unpaid and unstarted.

    Two rules deserve stating:

    PENDING_PAYMENT means different things by job type. An instant job in
    that state is already printed and merely unpaid, so its work is DONE.
    A production job waiting on its deposit has not been started at all.

    Payment is read from amounts rather than status. A job with a part
    payment against it — a 70/30 deposit, or a customer who paid 1,450 of
    1,555 — is DEPOSIT_PAID, not SETTLED, whatever its status says.
    """
    Job = apps.get_model('jobs', 'Job')

    WORK_BY_STATUS = {
        'DRAFT':            'RECEIVED',
        'PAID':             'RECEIVED',
        'CONFIRMED':        'RECEIVED',
        'IN_PROGRESS':      'IN_PRODUCTION',
        'READY':            'DONE',
        'OUT_FOR_DELIVERY': 'DONE',
        'COMPLETE':         'DONE',
        'CANCELLED':        'RECEIVED',
        'VOIDED':           'RECEIVED',
        'HALTED':           'IN_PRODUCTION',
        'SAMPLE_SENT':        'IN_PRODUCTION',
        'REVISION_REQUESTED': 'IN_PRODUCTION',
        'DESIGN_APPROVED':    'DONE',
    }

    HANDOVER_BY_STATUS = {
        'COMPLETE':         'HANDED_OVER',
        'OUT_FOR_DELIVERY': 'OUT_FOR_DELIVERY',
    }

    updated = 0
    for job in Job.objects.all().iterator(chunk_size=500):

        # ── Work ──────────────────────────────────────────────
        if job.status in ('PENDING_PAYMENT', 'INTAKE_HELD'):
            # Instant work is finished before it reaches the cashier;
            # production work has not begun.
            work = 'DONE' if job.job_type == 'INSTANT' else 'RECEIVED'
        else:
            work = WORK_BY_STATUS.get(job.status, 'RECEIVED')

        # ── Payment ───────────────────────────────────────────
        paid = job.amount_paid or 0
        cost = job.estimated_cost or 0

        if paid <= 0:
            payment = 'UNPAID'
        elif cost > 0 and paid < cost:
            payment = 'DEPOSIT_PAID'
        else:
            payment = 'SETTLED'

        # ── Handover ──────────────────────────────────────────
        handover = HANDOVER_BY_STATUS.get(job.status, 'AWAITING_COLLECTION')

        job.payment_state  = payment
        job.work_state     = work
        job.handover_state = handover
        job.save(update_fields=['payment_state', 'work_state', 'handover_state'])
        updated += 1

    print(f'  backfilled lifecycle states on {updated} job(s)')


def unbackfill(apps, schema_editor):
    """Reversing restores the field defaults; `status` is untouched throughout."""
    Job = apps.get_model('jobs', 'Job')
    Job.objects.all().update(
        payment_state  = 'UNPAID',
        work_state     = 'RECEIVED',
        handover_state = 'AWAITING_COLLECTION',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0020_job_handed_over_at_job_handed_over_by_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]