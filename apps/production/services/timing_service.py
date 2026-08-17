"""
Learn how long work actually takes, from what the job log already records.

Every observation comes from a gap between two work-state transitions.
IN_PRODUCTION → FINISHING is the print station; FINISHING → QUALITY_CHECK
is the finishing stations. The job log has recorded these all along; this
reads them.

Runs nightly rather than on transition. A wrong timing does not need to be
right within seconds, and analytics has no business in the path a cashier
takes to confirm a payment.

Two honesty measures matter here:

Halted time is excluded. A job stopped for two hours mid-print did not take
two hours to print, and counting it would teach the system that printing is
slow when the truth is that a machine broke.

Apportioned observations are marked as such. When a job both laminates and
binds, the finishing gap covers both and there is no way to know the split,
so it is divided by the seed estimates — which is a guess resting on a
guess. Those observations are weighted below clean single-station ones, so
that as unambiguous jobs accumulate they pull the figures toward truth
rather than being drowned by apportioned noise.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# A clean observation counts for this many apportioned ones. Apportioned
# figures split a real total by an estimated ratio, so they are right about
# the whole and unreliable about the parts.
CLEAN_WEIGHT       = 3
APPORTIONED_WEIGHT = 1

# Work-state transitions that represent time spent working, and the station
# code the elapsed time belongs to. RECEIVED → IN_PRODUCTION is a job
# waiting to be picked up, not work, and is deliberately absent.
WORK_GAPS = [
    ('IN_PRODUCTION', 'FINISHING',     'PRINT'),
    ('FINISHING',     'QUALITY_CHECK', 'FINISHING_GROUP'),
]

# Stations that a FINISHING gap may cover.
FINISHING_STATIONS = ['LAMINATE', 'BIND', 'CUT', 'FINISH']


class TimingService:

    @classmethod
    def observe_day(cls, day=None, dry_run=False) -> dict:
        """
        Read one day of completed transitions and update station timings.
        Returns a summary. Never raises on a single bad job — one
        unparseable job should not stop a night's learning.
        """
        from apps.jobs.models import Job

        day = day or (timezone.localdate() - timedelta(days=1))

        jobs = (
            Job.objects
            .filter(
                work_state='DONE',
                updated_at__date=day,
            )
            .exclude(status='CANCELLED')
            .select_related('branch')
            .prefetch_related('status_logs', 'halts', 'line_items__service')
        )

        observations = []
        for job in jobs:
            try:
                observations.extend(cls._observe_job(job))
            except Exception:
                logger.exception(
                    'TimingService: could not read job %s', job.pk
                )

        if not dry_run:
            for obs in observations:
                cls._apply(obs)

        return {
            'day':          day.isoformat(),
            'jobs_read':    len(jobs),
            'observations': len(observations),
            'clean':        sum(1 for o in observations if o['is_clean']),
            'apportioned':  sum(1 for o in observations if not o['is_clean']),
        }

    # ── Reading one job ──────────────────────────────────────────

    @classmethod
    def _observe_job(cls, job) -> list:
        """Every timing observation this job can honestly support."""
        logs = sorted(
            [l for l in job.status_logs.all() if l.axis == 'WORK'],
            key=lambda l: l.transitioned_at,
        )
        if len(logs) < 2:
            return []

        entered = {l.to_status: l.transitioned_at for l in logs}
        out = []

        for from_state, to_state, station_key in WORK_GAPS:
            start = entered.get(from_state)
            end   = entered.get(to_state)
            if not start or not end or end <= start:
                continue

            minutes = (end - start).total_seconds() / 60
            minutes -= cls._halted_minutes(job, start, end)
            if minutes <= 0:
                continue

            if station_key == 'PRINT':
                out.extend(cls._print_observation(job, minutes, start))
            else:
                out.extend(cls._finishing_observations(job, minutes, start))

        return out

    @staticmethod
    def _halted_minutes(job, start, end) -> float:
        """
        Minutes the job was halted within this window. A job stopped for a
        machine breakdown did not spend that time being worked on.
        """
        total = 0.0
        for halt in job.halts.all():
            halt_end = halt.resumed_at or end
            overlap_start = max(halt.halted_at, start)
            overlap_end   = min(halt_end, end)
            if overlap_end > overlap_start:
                total += (overlap_end - overlap_start).total_seconds() / 60
        return total

    # ── Turning elapsed time into per-unit figures ───────────────

    @classmethod
    def _print_observation(cls, job, minutes, at) -> list:
        """Print is one station, so the whole gap belongs to it."""
        units = cls._units_at_station(job, 'PRINT')
        if units <= 0:
            return []
        return [{
            'branch':   job.branch,
            'station':  'PRINT',
            'at':       at,
            'per_unit': minutes / units,
            'is_clean': True,
        }]

    @classmethod
    def _finishing_observations(cls, job, minutes, at) -> list:
        """
        The finishing gap covers laminating, binding, cutting and hand work
        together, with no way to know the split. One station involved gives
        a clean figure; several are apportioned by seed estimate, which is
        a guess resting on a guess and is marked accordingly.
        """
        from apps.production.models import ServiceStation

        involved = {}
        for li in job.line_items.all():
            routes = ServiceStation.objects.filter(
                service=li.service,
                station__code__in=FINISHING_STATIONS,
            ).select_related('station')
            for route in routes:
                code  = route.station.code
                qty   = li.quantity or 1
                entry = involved.setdefault(code, {'units': 0, 'estimate': 0.0})
                entry['units']    += qty
                entry['estimate'] += route.estimated_minutes(qty)

        if not involved:
            return []

        is_clean     = len(involved) == 1
        total_est    = sum(v['estimate'] for v in involved.values()) or 1.0

        out = []
        for code, v in involved.items():
            if v['units'] <= 0:
                continue
            share = minutes if is_clean else minutes * (v['estimate'] / total_est)
            out.append({
                'branch':   job.branch,
                'station':  code,
                'at':       at,
                'per_unit': share / v['units'],
                'is_clean': is_clean,
            })
        return out

    @staticmethod
    def _units_at_station(job, station_code) -> int:
        """Units passing through a station across all of a job's lines."""
        from apps.production.models import ServiceStation

        total = 0
        for li in job.line_items.all():
            passes = ServiceStation.objects.filter(
                service=li.service,
                station__code=station_code,
            ).exists()
            if passes:
                total += (li.quantity or 1) * (li.pages or 1)
        return total

    # ── Writing it down ──────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def _apply(cls, obs) -> None:
        """
        Fold one observation into the rolling average for its slot. Weighted
        so a clean observation moves the figure more than an apportioned one.
        """
        from apps.production.models import Station, StationTiming

        station = Station.objects.filter(code=obs['station']).first()
        if not station:
            return

        local  = timezone.localtime(obs['at'])
        weight = CLEAN_WEIGHT if obs['is_clean'] else APPORTIONED_WEIGHT

        timing, _ = StationTiming.objects.select_for_update().get_or_create(
            branch=obs['branch'],
            station=station,
            hour_of_day=local.hour,
            day_of_week=local.weekday(),
            defaults={
                'observed_minutes_per_unit': Decimal(str(round(obs['per_unit'], 4))),
                'sample_count':              weight,
                'last_observed_at':          obs['at'],
            },
        )

        # Weighted rolling mean. Old figures are never discarded, so a
        # single strange job cannot swing a well-observed slot.
        prior_n     = timing.sample_count or 0
        prior_value = float(timing.observed_minutes_per_unit or 0)
        new_n       = prior_n + weight
        new_value   = ((prior_value * prior_n) + (obs['per_unit'] * weight)) / new_n

        timing.observed_minutes_per_unit = Decimal(str(round(new_value, 4)))
        timing.sample_count              = new_n
        timing.last_observed_at          = obs['at']
        timing.save(update_fields=[
            'observed_minutes_per_unit', 'sample_count',
            'last_observed_at', 'updated_at',
        ])