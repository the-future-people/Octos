"""
The floor as the coordinator sees it: every machine with its line-up,
the one bench where all hand work is done, and anything waiting for a
machine to be chosen.

Each row carries how long until that step is done, counting everything
ahead of it, so the coordinator reads the whole line-up as time, not just
as order.
"""

from datetime import timedelta

from django.utils import timezone

from apps.jobs.models import JobStep


def _row(step, minutes, running_over, now):
    from apps.jobs.services.estimates import round_up

    job = step.job
    promise = job.estimated_ready_at
    done_by = now + timedelta(minutes=minutes)
    late = bool(promise and now > promise)

    return {
        'step':         step.pk,
        'state':        step.state,
        'station':      step.station.code,
        'by_hand':      step.by_hand,
        'line':         step.line_item.label or step.line_item.service.name,
        'job':          job.pk,
        'job_number':   job.job_number,
        'customer_name': job.customer.full_name if job.customer_id else 'Walk-in',
        'intake_channel': job.intake_channel,
        'promise':      promise.isoformat() if promise else None,
        'late':         late,
        'at_risk':      bool(promise and not late and done_by > promise),
        'minutes_until_done': round_up(minutes),
        'running_over': running_over,
        'reached_at':   step.reached_at.isoformat() if step.reached_at else None,
        'is_halted':    job.halts.filter(resumed_at__isnull=True).exists(),
        # Done on a line's last step is the final check, not a plain Done.
        'is_last':      not JobStep.objects.filter(
            line_item=step.line_item, sequence__gt=step.sequence,
        ).exists(),
    }


def _lane(steps, now):
    from apps.jobs.services.estimates import _left_on_machine

    rows, total = [], 0.0
    for step in steps:
        left, over = _left_on_machine(step, now)
        total += left
        rows.append(_row(step, total, over, now))
    return rows


def floor(branch, now=None):
    from apps.production.models import Machine, ServiceStation, Station
    from apps.jobs.services.steps import GONE, _current_only, fill, queue

    now = now or timezone.now()
    press, finishing = [], []

    machines = (
        Machine.objects
        .filter(branch=branch, is_active=True)
        .select_related('machine_type__station')
        .order_by('machine_type__station__sequence', 'name')
    )
    # Heal before reading: wherever a machine or the bench is free and work
    # is waiting, the front of its queue goes on. A cancelled job dropping
    # out, or anything else that left a gap, is closed the next time anyone
    # looks.
    bench_station = (
        Station.objects
        .filter(pk__in=ServiceStation.objects.filter(machine_type__isnull=True).values('station_id'))
        .order_by('sequence')
        .first()
    )
    for machine in machines:
        if machine.is_available:
            fill(branch, machine=machine)
    if bench_station is not None:
        fill(branch, station=bench_station)

    for machine in machines:
        entry = {
            'machine': {
                'id':           machine.pk,
                'name':         machine.name,
                'type':         machine.machine_type.name,
                'station':      machine.machine_type.station.code,
                'bench':        False,
                'is_available': machine.is_available,
                'reason':       machine.unavailable_reason,
            },
            'queue': _lane(queue(branch, machine=machine), now),
        }
        if machine.machine_type.station.code == 'PRINT':
            press.append(entry)
        else:
            finishing.append(entry)

    # One bench for all hand work: cutting, eyelets, packing.
    if bench_station is not None:
        finishing.append({
            'machine': {
                'id':           None,
                'name':         'Cutting / finishing',
                'type':         'Bench',
                'station':      'BENCH',
                'bench':        True,
                'is_available': True,
                'reason':       '',
            },
            'queue': _lane(queue(branch, station=bench_station), now),
        })

    stranded = _current_only(
        JobStep.objects
        .filter(job__branch=branch, machine__isnull=True, by_hand=False)
        .exclude(state=JobStep.State.DONE)
        .exclude(job__status__in=GONE)
        .select_related('job', 'line_item__service', 'station')
    )
    unassigned = [
        _row(step, float(step.expected_minutes), False, now)
        for step in stranded
    ]

    return {'press': press, 'finishing': finishing, 'unassigned': unassigned}