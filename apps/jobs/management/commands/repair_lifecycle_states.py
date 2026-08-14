"""
Repairs lifecycle axes on jobs whose payment was confirmed between the
backfill migration and the fix that made confirm_payment write them.

Those jobs sat at the model defaults — UNPAID / RECEIVED /
AWAITING_COLLECTION — regardless of what the cashier did, because the
legacy engine only ever wrote Job.status.

Applies the same derivation as the backfill and as
_apply_payment_axes: payment reads amounts, and a settled instant job
is a completed counter sale on all three axes.

Dry run by default. Pass --apply to write.

    python manage.py repair_lifecycle_states
    python manage.py repair_lifecycle_states --apply
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = 'Repair lifecycle axes on jobs left at defaults by the legacy payment path.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Write the changes. Without this the command only reports.',
        )
        parser.add_argument(
            '--branch',
            type=int,
            default=None,
            help='Restrict to one branch id.',
        )

    def handle(self, *args, **options):
        from apps.jobs.models import Job

        apply_changes = options['apply']
        branch_id     = options['branch']

        qs = Job.objects.exclude(status__in=['DRAFT', 'CANCELLED', 'INTAKE_HELD'])
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        planned = []

        for job in qs.iterator():
            paid = job.amount_paid    or Decimal('0')
            cost = job.estimated_cost or Decimal('0')

            if cost > 0 and paid >= cost:
                payment_state = 'SETTLED'
            elif paid > 0:
                payment_state = 'DEPOSIT_PAID'
            else:
                payment_state = 'UNPAID'

            work_state     = job.work_state
            handover_state = job.handover_state

            if job.job_type == 'INSTANT' and payment_state == 'SETTLED':
                work_state     = 'DONE'
                handover_state = 'HANDED_OVER'

            if (payment_state  != job.payment_state
                    or work_state     != job.work_state
                    or handover_state != job.handover_state):
                planned.append((job, payment_state, work_state, handover_state))

        if not planned:
            self.stdout.write(self.style.SUCCESS('Nothing to repair.'))
            return

        self.stdout.write(f'{len(planned)} job(s) need repair:\n')
        for job, p, w, h in planned[:20]:
            self.stdout.write(
                f'  {job.job_number:<24} '
                f'{job.payment_state} -> {p} | '
                f'{job.work_state} -> {w} | '
                f'{job.handover_state} -> {h}'
            )
        if len(planned) > 20:
            self.stdout.write(f'  … and {len(planned) - 20} more')

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                '\nDry run. Re-run with --apply to write these changes.'
            ))
            return

        # No JobStatusLog rows are written here. These transitions never
        # happened as events — this is a correction of state the system
        # failed to record, and inventing an audit trail for it with a
        # timestamp of today would be a lie about when the work moved.
        with transaction.atomic():
            for job, p, w, h in planned:
                job.payment_state  = p
                job.work_state     = w
                job.handover_state = h
                job.save(update_fields=[
                    'payment_state', 'work_state', 'handover_state', 'updated_at',
                ])

        self.stdout.write(self.style.SUCCESS(
            f'\nRepaired {len(planned)} job(s).'
        ))