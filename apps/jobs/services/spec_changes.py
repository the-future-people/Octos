"""
Correcting what a customer ordered, during inspection, with their say-so.

The rules live here and nowhere else:

- Only the coordinator holding the inspection claim may change a job,
  and only while it is still being inspected. Once it is on the press,
  the order is what it is.
- The customer's agreement is required, in words. The call is made on
  the recorded company line; this is what was agreed on it.
- Only fields the order already has. A coordinator corrects a size or a
  finish; inventing fields the service never asked for is not a
  correction.
- Nothing that sets the price. Quantity, sets and pages are counts the
  price was built from, and the price was paid. A different quantity
  goes back through the counter, where money is handled.
- The price columns are never written.

Every field changed is recorded with its old and new value, who, when
and what the customer said, in the same transaction as the change.
"""

from django.db import transaction

from apps.jobs.models import Job, JobLineItem, JobSpecChange
from apps.jobs.services.inspection import claim_is_live

# Line columns that describe the work, not the money.
COLUMN_FIELDS = {'paper_size', 'sides', 'is_color'}

# Counts the price was built from. Never changed here, whether as a
# column or tucked inside the specification (the model copies a spec
# 'pages' into the priced page count).
PRICED = {'quantity', 'sets', 'pages', 'unit_price', 'line_total'}

PAPER_SIZE_MAX = 10


class SpecChangeRefused(Exception):
    """The change is not allowed, and the message says why."""


def change_specs(job_id, line_id, changes, customer_response, actor):
    response = (customer_response or '').strip()
    if not response:
        raise SpecChangeRefused(
            'Record what the customer agreed to before changing their order.'
        )
    if not isinstance(changes, dict) or not changes:
        raise SpecChangeRefused('Nothing to change.')

    with transaction.atomic():
        job = Job.objects.select_for_update().filter(pk=job_id).first()
        if job is None:
            raise SpecChangeRefused('That job does not exist.')

        if not (claim_is_live(job) and job.inspecting_by_id == actor.pk):
            raise SpecChangeRefused(
                f'Open {job.job_number} for inspection before changing it.'
            )
        if job.work_state != 'RECEIVED' or job.is_verified:
            raise SpecChangeRefused(
                f'{job.job_number} has already been cleared. '
                f'Its order can no longer be changed here.'
            )

        line = (
            JobLineItem.objects
            .select_for_update()
            .filter(pk=line_id, job=job)
            .first()
        )
        if line is None:
            raise SpecChangeRefused('That line is not on this job.')

        specs = dict(line.specifications or {})
        recorded = []
        touched = set()

        for field, new in changes.items():
            if field in PRICED:
                raise SpecChangeRefused(
                    f'{field.replace("_", " ").capitalize()} sets the price. '
                    f'A different {field.replace("_", " ")} goes back through the counter.'
                )

            if field in COLUMN_FIELDS:
                if field == 'is_color':
                    new = bool(new)
                elif field == 'sides':
                    if new not in dict(JobLineItem.SIDES_CHOICES):
                        raise SpecChangeRefused('Sides must be single or double.')
                elif field == 'paper_size':
                    new = str(new).strip().upper()
                    if not new or len(new) > PAPER_SIZE_MAX:
                        raise SpecChangeRefused('That paper size is not valid.')
                old = getattr(line, field)
                if old == new:
                    continue
                setattr(line, field, new)
                touched.add(field)

            elif field in specs:
                old = specs[field]
                if old == new:
                    continue
                specs[field] = new
                touched.add('specifications')

            else:
                raise SpecChangeRefused(
                    f'This order has no "{field}" to change.'
                )

            recorded.append(JobSpecChange(
                job=job, line_item=line, field=field,
                old_value=old, new_value=new,
                customer_response=response, changed_by=actor,
            ))

        if not recorded:
            return []

        line.specifications = specs
        line.save(update_fields=[*sorted(touched), 'updated_at'])
        JobSpecChange.objects.bulk_create(recorded)
            # The customer changed the job (a corrected size, a fixed file): the
        # clock starts again from their change. Not the shop's delay, so no
        # apology and no mark against the promise score. After the change is
        # saved, so the new estimate reads the job as it now is.
        if recorded and job.estimated_ready_at:
            from django.db import transaction
            from apps.jobs.models import Job
            from apps.jobs.services.lateness import restart_for_customer
            changed_id = job.pk
            transaction.on_commit(lambda: restart_for_customer(Job.objects.get(pk=changed_id)))
            
        return recorded