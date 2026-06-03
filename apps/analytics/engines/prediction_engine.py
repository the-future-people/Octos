# apps/analytics/engines/prediction_engine.py
"""
EOD Revenue Prediction Engine
==============================
Predicts end-of-day job count and revenue for an open branch sheet.

Algorithm — three layered signals:

  1. Historical hourly curve (day-of-week aware)
     For the current weekday, compute the average fraction of daily jobs
     that occur in each hour across all past sheets. This gives a
     normalised distribution: "on Fridays, 8% of jobs happen at 9am".

  2. Today's deviation factor
     Compare today's actual jobs so far against what the historical
     curve predicts for this time of day. If today is running 30% above
     the historical Friday pace, project the remaining hours at +30%.

  3. Revenue weighting
     Multiply predicted remaining jobs by today's average job value
     to produce a revenue prediction.

Confidence:
  Increases linearly with hours elapsed as a fraction of the historical
  operating window. At 8am confidence is low (~10%). By 3pm it's ~60%.
  By 6pm it's ~85%.

Fallback:
  If insufficient historical data exists for the current weekday
  (< 3 data points), falls back to a simple linear extrapolation.
  This prevents garbage predictions on new branches.

Design rules:
  - PredictionEngine never writes to the DB
  - All reads are lightweight — no heavy aggregations at request time
  - Called by SheetSummaryService._build_pace() only
  - Returns a dict that extends the existing pace payload
"""

import logging
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum historical sheets needed before switching from
# linear fallback to the curve-based prediction
MIN_HISTORY_SHEETS = 3

# Historical operating window end hour — derived from data as avg last-job hour
# per weekday. Used when we can't compute it dynamically.
DEFAULT_CLOSE_HOUR = 19  # 7pm


class PredictionEngine:

    def __init__(self, branch):
        self.branch = branch

    # ── Public API ────────────────────────────────────────────────────────────

    def predict(self, sheet, current_jobs: int, avg_job_value: float) -> dict:
        """
        Predict EOD job count and revenue for an open sheet.

        Args:
            sheet          : DailySalesSheet (must be OPEN)
            current_jobs   : int — jobs recorded so far today
            avg_job_value  : float — revenue per completed job today

        Returns:
            {
                predicted_jobs_eod    : int
                predicted_revenue_eod : float
                confidence_pct        : int  (0-95)
                method                : str  ('curve' | 'linear')
                remaining_hours       : float
                close_hour            : int
            }
        """
        from django.utils import timezone

        now        = timezone.now()
        current_hour = now.hour + now.minute / 60.0
        weekday    = sheet.date.weekday()  # 0=Mon, 6=Sun

        try:
            history = self._load_history(weekday)

            if len(history['sheets']) < MIN_HISTORY_SHEETS:
                return self._linear_predict(
                    current_jobs, avg_job_value, current_hour,
                    history['close_hour'], method='linear_fallback'
                )

            return self._curve_predict(
                current_jobs, avg_job_value, current_hour,
                history, weekday,
            )

        except Exception:
            logger.exception(
                'PredictionEngine: prediction failed for sheet %s — using linear fallback',
                sheet.pk,
            )
            return self._linear_predict(
                current_jobs, avg_job_value, current_hour,
                DEFAULT_CLOSE_HOUR, method='linear_fallback'
            )

    # ── History loader ────────────────────────────────────────────────────────

    def _load_history(self, weekday: int) -> dict:
        """
        Load historical job data for the given weekday.

        Returns:
            {
                sheets        : list of {date, total_jobs, hourly: {hour: count}}
                hourly_curve  : dict {hour: avg_fraction}  — normalised 0..1
                avg_total     : float — avg total jobs on this weekday
                close_hour    : int   — avg last-job hour for this weekday
            }
        """
        from apps.jobs.models import Job
        from apps.finance.models import DailySalesSheet
        from django.db.models import Count, Max
        from django.db.models.functions import ExtractHour, TruncDate
        from collections import defaultdict

        # Get all closed sheets for this weekday
        past_sheets = DailySalesSheet.objects.filter(
            branch  = self.branch,
            date__week_day = (weekday + 2) % 7 or 7,
            # Django week_day: 1=Sun, 2=Mon ... 7=Sat
            # weekday: 0=Mon, 6=Sun
            # Conversion: Django week_day = (weekday + 2) if weekday < 6 else 1
        ).exclude(
            status=DailySalesSheet.Status.OPEN,
        ).order_by('-date')[:12]  # last 12 matching weekdays

        if not past_sheets:
            return {
                'sheets'      : [],
                'hourly_curve': {},
                'avg_total'   : 0,
                'close_hour'  : DEFAULT_CLOSE_HOUR,
            }

        sheet_ids   = [s.pk for s in past_sheets]
        sheet_dates = {s.pk: s.date for s in past_sheets}

        # Hourly job counts per sheet
        hourly_qs = Job.objects.filter(
            daily_sheet__in = sheet_ids,
            status          = 'COMPLETE',
        ).annotate(
            hour = ExtractHour('created_at'),
        ).values(
            'daily_sheet', 'hour'
        ).annotate(
            count = Count('id')
        ).order_by('daily_sheet', 'hour')

        # Build per-sheet data
        sheet_data = defaultdict(lambda: {'hourly': defaultdict(int), 'total': 0})
        for row in hourly_qs:
            sid = row['daily_sheet']
            sheet_data[sid]['hourly'][row['hour']] += row['count']
            sheet_data[sid]['total'] += row['count']

        sheets = [
            {
                'date'   : sheet_dates[sid],
                'total'  : data['total'],
                'hourly' : dict(data['hourly']),
            }
            for sid, data in sheet_data.items()
            if data['total'] > 0
        ]

        if not sheets:
            return {
                'sheets'      : [],
                'hourly_curve': {},
                'avg_total'   : 0,
                'close_hour'  : DEFAULT_CLOSE_HOUR,
            }

        # Build normalised hourly curve — average fraction per hour
        hour_fractions = defaultdict(list)
        for s in sheets:
            total = s['total']
            if total == 0:
                continue
            for hour, count in s['hourly'].items():
                hour_fractions[hour].append(count / total)

        hourly_curve = {
            hour: sum(fracs) / len(fracs)
            for hour, fracs in hour_fractions.items()
        }

        # Normalise so curve sums to 1.0
        curve_sum = sum(hourly_curve.values())
        if curve_sum > 0:
            hourly_curve = {h: v / curve_sum for h, v in hourly_curve.items()}

        avg_total = sum(s['total'] for s in sheets) / len(sheets)

        # Average close hour — weighted by recency
        close_hours = []
        for s in sheets:
            if s['hourly']:
                close_hours.append(max(s['hourly'].keys()))
        close_hour = int(sum(close_hours) / len(close_hours)) if close_hours else DEFAULT_CLOSE_HOUR

        return {
            'sheets'      : sheets,
            'hourly_curve': hourly_curve,
            'avg_total'   : avg_total,
            'close_hour'  : close_hour,
        }

    # ── Curve-based prediction ────────────────────────────────────────────────

    def _curve_predict(
        self,
        current_jobs: int,
        avg_job_value: float,
        current_hour: float,
        history: dict,
        weekday: int,
    ) -> dict:
        """
        Use historical hourly curve + today's deviation to predict EOD.
        """
        curve      = history['hourly_curve']
        close_hour = history['close_hour']
        avg_total  = history['avg_total']

        if not curve or avg_total == 0:
            return self._linear_predict(
                current_jobs, avg_job_value, current_hour, close_hour, 'linear'
            )

        # Fraction of jobs that historically occur UP TO current hour
        elapsed_fraction = sum(
            frac for hour, frac in curve.items()
            if hour <= int(current_hour)
        )

        # Deviation factor — how today compares to historical baseline
        if elapsed_fraction > 0.05:  # only apply once we have enough signal
            expected_so_far = avg_total * elapsed_fraction
            deviation_factor = current_jobs / expected_so_far if expected_so_far > 0 else 1.0
            # Cap deviation to prevent wild swings — max 2x or 0.3x
            deviation_factor = max(0.3, min(2.0, deviation_factor))
        else:
            deviation_factor = 1.0

        # Fraction of jobs that historically occur AFTER current hour
        remaining_fraction = sum(
            frac for hour, frac in curve.items()
            if hour > int(current_hour)
        )

        # Predicted remaining jobs — apply deviation factor
        predicted_remaining = avg_total * remaining_fraction * deviation_factor

        predicted_total   = current_jobs + predicted_remaining
        predicted_revenue = predicted_total * avg_job_value if avg_job_value else 0

        # Confidence — fraction of operating day elapsed
        operating_hours  = max(close_hour - 8, 1)  # branch opens ~8am
        hours_elapsed    = max(current_hour - 8, 0)
        elapsed_pct      = min(hours_elapsed / operating_hours, 1.0)
        # Confidence scales from 15% at open to 95% near close
        confidence = int(15 + (elapsed_pct * 80))
        confidence = min(confidence, 95)

        remaining_hours = max(close_hour - current_hour, 0)

        return {
            'predicted_jobs_eod'    : round(predicted_total),
            'predicted_revenue_eod' : round(predicted_revenue, 2),
            'confidence_pct'        : confidence,
            'method'                : 'curve',
            'deviation_factor'      : round(deviation_factor, 2),
            'remaining_hours'       : round(remaining_hours, 1),
            'close_hour'            : close_hour,
        }

    # ── Linear fallback ───────────────────────────────────────────────────────

    def _linear_predict(
        self,
        current_jobs: int,
        avg_job_value: float,
        current_hour: float,
        close_hour: int,
        method: str = 'linear',
    ) -> dict:
        """
        Simple linear extrapolation — used when insufficient history exists.
        """
        hours_elapsed   = max(current_hour - 8, 0.25)
        hours_remaining = max(close_hour - current_hour, 0)
        jobs_per_hour   = current_jobs / hours_elapsed if hours_elapsed > 0 else 0

        predicted_remaining = jobs_per_hour * hours_remaining
        predicted_total     = current_jobs + predicted_remaining
        predicted_revenue   = predicted_total * avg_job_value if avg_job_value else 0

        operating_hours = max(close_hour - 8, 1)
        confidence      = int(15 + (min(hours_elapsed / operating_hours, 1.0) * 50))

        return {
            'predicted_jobs_eod'    : round(predicted_total),
            'predicted_revenue_eod' : round(predicted_revenue, 2),
            'confidence_pct'        : confidence,
            'method'                : method,
            'deviation_factor'      : 1.0,
            'remaining_hours'       : round(hours_remaining, 1),
            'close_hour'            : close_hour,
        }