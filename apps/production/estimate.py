"""
When a job will be ready.

Three questions, answered separately so each can be wrong on its own:

    work_minutes   how long this job takes
    queue_minutes  how much is already in front of it
    ready_at       what time that lands on, given the branch is shut
                   overnight and all day Sunday

The third is the one that catches people out. Three hours of work
accepted at six in the evening is not ready at nine — the branch closed
at half seven, and the rest is done in the morning.

The timings come from ServiceStation, which someone measured on the
floor. Nothing here derives them, and nothing here should: a figure
invented in code is a figure nobody can correct.

Every estimate is a guess until there is history to check it against.
The thing that makes this accurate is recording what actually happened
and comparing, which is why estimated_ready_at is stored on the job
rather than computed fresh each time it is asked for.
"""

import datetime
import logging
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

# Work that is on the floor or waiting for it. A job that is done, or
# halted, is in nobody's way.
ACTIVE_WORK_STATES = ('RECEIVED', 'IN_PRODUCTION', 'FINISHING', 'QUALITY_CHECK')


def work_minutes(job):
    """
    How long this job takes, summed across the stations its services
    pass through.

    Returns None when a service has no route through the floor. Zero
    would say the job is ready immediately, which is a worse answer
    than admitting we do not know.
    """
    from apps.production.models import ServiceStation

    total = Decimal('0')
    mapped_any = False

    for line in job.line_items.select_related('service'):
        routes = ServiceStation.objects.filter(
            service=line.service,
        ).order_by('sequence')

        if not routes.exists():
            logger.info(
                'No floor route for %s on %s — cannot estimate',
                line.service.code, job.job_number,
            )
            return None

        mapped_any = True
        units = _units(line)
        pieces = Decimal(str(line.pages or 1))

        for route in routes:
            # Setup is per piece, not per job: a second banner is loaded,
            # cut and hemmed again. Only the per-unit part scales with
            # how big each one is.
            total += (route.setup_minutes + route.minutes_per_unit * units) * pieces

    return float(total) if mapped_any else None


def queue_minutes(branch, station_people=None):
    """
    How much work is already in front of a new job at this branch.

    Divided by the people at each station, because capacity is people
    rather than machines: two at the printer means two banners print at
    once, and one at finishing means everything funnels through them.

    A job whose service has no route contributes nothing rather than
    stopping the sum — the queue is still worth knowing even when one
    job in it cannot be estimated.
    """
    from apps.jobs.models import Job, JobHalt
    from apps.production.models import BranchStation, ServiceStation

    halted = set(
        JobHalt.objects.filter(
            resumed_at__isnull=True,
        ).values_list('job_id', flat=True)
    )

    jobs = (
        Job.objects
        .filter(branch=branch, work_state__in=ACTIVE_WORK_STATES)
        .exclude(status__in=['CANCELLED', 'DRAFT', 'VOIDED'])
        .exclude(pk__in=halted)
        .prefetch_related('line_items__service')
    )

    # Minutes waiting at each station, so a bottleneck shows as itself
    # rather than being averaged away across the floor.
    by_station = {}

    for job in jobs:
        for line in job.line_items.all():
            routes = ServiceStation.objects.filter(
                service=line.service,
            ).select_related('station')

            units = _units(line)
            pieces = Decimal(str(line.pages or 1))

            for route in routes:
                minutes = (
                    route.setup_minutes + route.minutes_per_unit * units
                ) * pieces
                by_station.setdefault(route.station, Decimal('0'))
                by_station[route.station] += minutes

    if not by_station:
        return 0.0

    total = Decimal('0')
    for station, minutes in by_station.items():
        people = (
            station_people.get(station.code)
            if station_people
            else BranchStation.people_at(branch, station)
        )
        total += minutes / Decimal(max(1, people or 1))

    return float(total)


def ready_at(branch, minutes, start=None):
    """
    Walk `minutes` of work forward from `start` through the branch's
    trading hours.

    Not elapsed time. A branch open 07:30 to 19:30 has twelve hours in
    a day, so three hours of work starting at six in the evening takes
    until nine the next morning. Sunday is skipped entirely.
    """
    start = start or timezone.now()
    remaining = Decimal(str(minutes))

    opens = branch.opening_time or datetime.time(7, 30)
    closes = branch.closing_time or datetime.time(19, 30)

    cursor = timezone.localtime(start)

    # Guard rather than loop forever: a branch with no open hours, or a
    # job longer than a working fortnight, should give up and say so.
    for _ in range(60):
        if _is_closed_day(cursor):
            cursor = _start_of_next_day(cursor, opens)
            continue

        day_opens = cursor.replace(
            hour=opens.hour, minute=opens.minute, second=0, microsecond=0,
        )
        day_closes = cursor.replace(
            hour=closes.hour, minute=closes.minute, second=0, microsecond=0,
        )

        if cursor < day_opens:
            cursor = day_opens
        if cursor >= day_closes:
            cursor = _start_of_next_day(cursor, opens)
            continue

        available = Decimal((day_closes - cursor).total_seconds()) / 60

        if remaining <= available:
            return cursor + datetime.timedelta(minutes=float(remaining))

        remaining -= available
        cursor = _start_of_next_day(cursor, opens)

    logger.warning(
        'Could not place %s minutes of work at %s within sixty days',
        minutes, branch.code,
    )
    return None


def estimate_for(job, start=None):
    """
    The whole answer for one job: its own work, what is ahead of it, and
    the moment that lands on.

    Returns None where the job cannot be estimated, rather than a time
    that looks confident and means nothing.
    """
    own = work_minutes(job)
    if own is None:
        return None

    ahead = queue_minutes(job.branch)
    return ready_at(job.branch, own + ahead, start=start)


def _units(line):
    """
    What the per-unit figure is counted in.

    A square foot for anything priced by area, a page or a piece for
    everything else. The line item already knows which, because the
    service's unit decides how it was priced.
    """
    unit = (line.service.unit or '').upper().replace('PER_', '')

    if unit in ('SQFT', 'SQCM', 'SQM'):
        specs = line.specifications or {}
        width = specs.get('width_in')
        height = specs.get('height_in')
        if width and height:
            return (Decimal(str(width)) * Decimal(str(height))) / Decimal('144')
        # Priced by area with no dimensions recorded: the quantity is
        # the area, which is what the pricing engine was given.
        return Decimal(str(line.quantity or 1))

    return Decimal(str(line.quantity or 1))


def _is_closed_day(moment):
    """Sunday. The branch does not trade, so nothing is made."""
    return moment.weekday() == 6


def _start_of_next_day(moment, opens):
    nxt = moment + datetime.timedelta(days=1)
    return nxt.replace(
        hour=opens.hour, minute=opens.minute, second=0, microsecond=0,
    )