"""
Predict when a job will be ready.

The promise, not the average. A customer told "about two hours, ready by
1:30" wants that to be true, and being late costs far more than being
early — so the figure is deliberately buffered above the expected time.
The buffer is a flat multiplier today and should become a measured
percentile once there is enough spread to compute one.

The calculation is deliberately simple: what is queued ahead at each
station this job touches, plus this job's own work, corrected by what the
branch actually achieves at that hour. Machine contention, hand finishing,
interruptions and everything else unmodelled is absorbed by the correction
factor rather than guessed at. The gap between predicted and actual is what
teaches the system.

Opening hours are walked rather than ignored. Three hours of work starting
at 6pm does not finish at 9pm — the branch closed at 7:30.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

# Under-promise. A flat multiplier until there is variance to measure, at
# which point this should become a percentile of the observed distribution.
BUFFER_MULTIPLIER = 1.3

# Work already under way continues past closing until it is done, but
# nothing new starts. Current practice at Westland, not a fixed principle —
# expect this to change once there are bigger machines, more space and more
# hands.
CLOSING_GRACE_MINUTES = 10

# The week runs Monday to Saturday. Sunday is not a working day.
SUNDAY = 6


@dataclass
class Prediction:
    ready_at: datetime
    total_minutes: float
    queue_minutes: float
    own_minutes: float
    is_next_day: bool
    confidence: str                      # 'measured' | 'estimated'
    per_station: dict = field(default_factory=dict)

    @property
    def is_reliable(self) -> bool:
        return self.confidence == 'measured'


class PredictionService:

    def __init__(self, branch):
        self.branch = branch

    # ── Public ───────────────────────────────────────────────────

    def predict(self, line_items, at=None) -> Prediction:
        """
        When a job of these line items would be ready if accepted now.

        line_items is a list of (service, quantity, pages) — it does not
        need a saved job, so a customer can be quoted before committing.
        """
        at = at or timezone.localtime()

        own, per_station = self._own_minutes(line_items, at)
        queue            = self._queue_minutes(per_station.keys())

        total = (own + queue) * BUFFER_MULTIPLIER
        start = self._next_working_moment(at)
        ready = self._add_working_minutes(start, total)

        return Prediction(
            ready_at      = ready,
            total_minutes = round(total, 1),
            queue_minutes = round(queue, 1),
            own_minutes   = round(own, 1),
            is_next_day   = ready.date() > at.date(),
            confidence    = self._confidence(per_station.keys(), at),
            per_station   = per_station,
        )

    # ── This job's own work ──────────────────────────────────────

    def _own_minutes(self, line_items, at) -> tuple:
        """
        Minutes of work this job needs, and how it splits across stations.
        Uses what the branch actually achieves where that is known, and the
        seed figure where it is not.
        """
        from apps.production.models import ServiceStation

        per_station = {}

        for service, quantity, pages in line_items:
            routes = (
                ServiceStation.objects
                .filter(service=service)
                .select_related('station')
                .order_by('sequence')
            )
            for route in routes:
                code = route.station.code
                # Sheets at the press, documents at the binder. A ten-page
                # document bound once is ten sheets to print and one to bind.
                units = quantity * pages if code == 'PRINT' else quantity

                observed = self._observed_per_unit(route.station, at=at)
                per_unit = observed if observed is not None else float(route.minutes_per_unit)

                minutes = float(route.setup_minutes) + per_unit * units
                per_station[code] = per_station.get(code, 0.0) + minutes

        return sum(per_station.values()), per_station

    # ── What is already ahead ────────────────────────────────────

    def _queue_minutes(self, station_codes) -> float:
        """
        Work already accepted that must clear before this job runs.

        First in, first out by creation. There is no priority or due date
        driving the order today, and creation order is what actually
        happens on the floor.

        Stations run independently, so a job waits for the busiest station
        it needs rather than the sum of all of them — that is what a
        pipeline means.
        """
        from apps.jobs.models import Job
        from apps.production.models import ServiceStation

        if not station_codes:
            return 0.0

        ahead = (
            Job.objects
            .filter(
                branch=self.branch,
                work_state__in=['RECEIVED', 'IN_PRODUCTION', 'FINISHING', 'QUALITY_CHECK'],
            )
            .exclude(status__in=['CANCELLED', 'DRAFT'])
            .prefetch_related('line_items__service', 'halts')
            .order_by('created_at')
        )

        per_station = {code: 0.0 for code in station_codes}

        for job in ahead:
            # A halted job is not consuming station time. It will when it
            # resumes, but predicting when that happens would be a guess.
            if any(h.resumed_at is None for h in job.halts.all()):
                continue

            for li in job.line_items.all():
                routes = (
                    ServiceStation.objects
                    .filter(service=li.service, station__code__in=station_codes)
                    .select_related('station')
                )
                for route in routes:
                    code  = route.station.code
                    units = (li.quantity or 1) * (li.pages or 1) if code == 'PRINT' else (li.quantity or 1)

                    observed = self._observed_per_unit(route.station)
                    per_unit = observed if observed is not None else float(route.minutes_per_unit)

                    per_station[code] += float(route.setup_minutes) + per_unit * units

        # The busiest station this job touches, not the sum.
        return max(per_station.values()) if per_station else 0.0

    # ── What the branch actually achieves ────────────────────────

    def _observed_per_unit(self, station, at=None):
        """
        Measured minutes per unit for this branch and station at this hour,
        or None where there is not enough evidence to quote. A number the
        branch cannot hit is worse than no number.
        """
        from apps.production.models import StationTiming

        at = at or timezone.localtime()
        timing = StationTiming.objects.filter(
            branch=self.branch,
            station=station,
            hour_of_day=at.hour,
            day_of_week=at.weekday(),
        ).first()

        if timing and timing.is_reliable:
            return float(timing.observed_minutes_per_unit)
        return None

    def _confidence(self, station_codes, at) -> str:
        """
        Measured only when every station involved has enough observations.
        One unmeasured station makes the whole figure an estimate.
        """
        from apps.production.models import Station, StationTiming

        for code in station_codes:
            station = Station.objects.filter(code=code).first()
            if not station:
                return 'estimated'
            timing = StationTiming.objects.filter(
                branch=self.branch, station=station,
                hour_of_day=at.hour, day_of_week=at.weekday(),
            ).first()
            if not timing or not timing.is_reliable:
                return 'estimated'
        return 'measured'

    # ── Walking the working day ──────────────────────────────────

    def _next_working_moment(self, at) -> datetime:
        """
        When work on this job could actually begin.

        Arriving within the closing grace still gets worked on tonight —
        the branch is winding down but people are there. Arriving at or
        after closing is tomorrow's work, and the customer is told so when
        they order rather than discovering it later.
        """
        opening = self.branch.opening_time
        closing = self.branch.closing_time

        # Arriving before closing still gets worked on — the branch is
        # winding down but people are there. At or after closing is
        # tomorrow's work, and the customer is told when they order.
        cutoff = timezone.make_aware(
            datetime.combine(at.date(), closing), at.tzinfo
        )

        if at.weekday() == SUNDAY:
            return self._opening_on(self._next_working_day(at.date()), at)

        if at.time() < opening:
            return timezone.make_aware(
                datetime.combine(at.date(), opening), at.tzinfo
            )

        if at >= cutoff:
            return self._opening_on(self._next_working_day(at.date()), at)

        return at

    def _add_working_minutes(self, start, minutes) -> datetime:
        """
        Walk forward through opening hours. Work under way continues past
        closing until it is done, but nothing new starts — so only the
        final stretch may run late.
        """
        opening = self.branch.opening_time
        closing = self.branch.closing_time

        current   = start
        remaining = minutes
        guard     = 0

        while remaining > 0 and guard < 30:
            guard += 1

            close_at = timezone.make_aware(
                datetime.combine(current.date(), closing), current.tzinfo
            )
            available = (close_at - current).total_seconds() / 60

            if remaining <= available:
                return current + timedelta(minutes=remaining)

            # Work that has already started runs to the end of the day and
            # the rest carries over to the next opening.
            remaining -= available
            current = self._opening_on(
                self._next_working_day(current.date()), current
            )

        logger.warning(
            'PredictionService: gave up walking the calendar for branch %s',
            self.branch.pk,
        )
        return current

    @staticmethod
    def _next_working_day(from_date):
        """The next day the branch trades. The week runs Monday to Saturday."""
        nxt = from_date + timedelta(days=1)
        while nxt.weekday() == SUNDAY:
            nxt += timedelta(days=1)
        return nxt

    def _opening_on(self, day, reference) -> datetime:
        return timezone.make_aware(
            datetime.combine(day, self.branch.opening_time), reference.tzinfo
        )