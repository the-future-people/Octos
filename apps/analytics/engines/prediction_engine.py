# apps/analytics/engines/prediction_engine.py
"""
EOD Prediction Engine v2
========================
Predicts end-of-day job count and revenue as a confidence interval.

Result format:
    {
        'jobs_low'        : int,    # pessimistic EOD job count
        'jobs_high'       : int,    # optimistic EOD job count
        'jobs_point'      : int,    # central estimate
        'revenue_low'     : float,  # GHS lower bound
        'revenue_high'    : float,  # GHS upper bound
        'revenue_point'   : float,  # GHS central estimate
        'confidence_pct'  : int,    # 0–94
        'method'          : str,    # 'curve' | 'linear_fallback'
        'remaining_hours' : float,
        'close_hour'      : int,
        'weather_factor'  : float,  # 0.65–1.0 multiplier applied
        'weather_note'    : str,    # human-readable weather impact
        'deviation_factor': float,
        'data_weeks'      : int,    # weeks of history used
    }

Algorithm — five layered signals:

  1. Historical hourly curve (day-of-week + week-of-month aware)
     Reads HourlySheetSnapshot records for the same weekday.
     Computes mean and standard deviation per hour slot.
     Normalises into a probability distribution over the operating day.

  2. Today's deviation factor
     Compares actuals so far against historical expectation.
     Capped at 0.3x–2.0x to prevent wild swings.

  3. Week-of-month adjustment
     First week of month (salary week) historically busier.
     Blended at 20% weight against the weekday baseline.

  4. Weather discount
     Fetches today's forecast from Open-Meteo (free, no key).
     Heavy rain → 0.65x, light rain → 0.85x, harmattan → 0.90x.
     Applied to remaining hours only — actuals already happened.

  5. Confidence interval construction
     Lower bound: pessimistic pace (historical slow-day rate)
     Upper bound: optimistic pace (current momentum held)
     Bounds narrow as day progresses (uncertainty reduces).
     Confidence formula accounts for data volume, pace stability,
     weather uncertainty, and elapsed day fraction.

Design rules:
  - PredictionEngine never writes to the DB
  - All reads use HourlySheetSnapshot — no raw Job queries at request time
  - Falls back to linear extrapolation if < 3 historical sheets exist
  - Never claims > 94% confidence
"""

import logging
import math
from collections import defaultdict

logger = logging.getLogger(__name__)

MIN_HISTORY_SHEETS  = 3
DEFAULT_CLOSE_HOUR  = 19
DEFAULT_OPEN_HOUR   = 8
ACCRA_LAT           = 5.6037
ACCRA_LNG           = -0.1870
WEEK_OF_MONTH_WEIGHT = 0.20   # blend weight for week-of-month adjustment


class PredictionEngine:

    def __init__(self, branch):
        self.branch = branch

    # ── Public API ────────────────────────────────────────────────────────────

    def predict(self, sheet, current_jobs: int, current_revenue: float) -> dict:
        """
        Predict EOD job count and revenue interval for an open sheet.

        Args:
            sheet           : DailySalesSheet (must be OPEN)
            current_jobs    : int   — jobs recorded so far today
            current_revenue : float — revenue collected so far today

        Returns:
            Full prediction dict (see module docstring).
        """
        from django.utils import timezone

        now          = timezone.now()
        current_hour = now.hour + now.minute / 60.0
        weekday      = sheet.date.weekday()
        day          = sheet.date.day
        week_of_month = (day - 1) // 7 + 1

        avg_job_value = (
            current_revenue / current_jobs
            if current_jobs > 0 else 0.0
        )

        try:
            history = self._load_history(weekday)
            weather = self._get_weather_factor(sheet.date, current_hour)

            if len(history['sheets']) < MIN_HISTORY_SHEETS:
                result = self._linear_predict(
                    current_jobs, current_revenue, avg_job_value,
                    current_hour, history['close_hour'],
                )
                result['weather_factor'] = weather['factor']
                result['weather_note']   = weather['note']
                result['data_weeks']     = len(history['sheets'])
                return result

            return self._curve_predict(
                current_jobs, current_revenue, avg_job_value,
                current_hour, history, week_of_month, weather,
            )

        except Exception:
            logger.exception(
                'PredictionEngine.predict failed for sheet %s — linear fallback',
                sheet.pk,
            )
            return self._linear_predict(
                current_jobs, current_revenue, avg_job_value,
                current_hour, DEFAULT_CLOSE_HOUR,
            )

    # ── History loader ────────────────────────────────────────────────────────

    def _load_history(self, weekday: int) -> dict:
        """
        Load HourlySheetSnapshot records for this weekday.
        Returns mean, std_dev, and per-sheet data for curve construction.
        """
        from apps.analytics.models import HourlySheetSnapshot
        from django.db.models import Avg, StdDev, Sum

        # Distinct sheets for this branch + weekday
        sheet_ids = list(
            HourlySheetSnapshot.objects.filter(
                branch  = self.branch,
                weekday = weekday,
            ).values_list('daily_sheet', flat=True).distinct().order_by('-date')[:16]
        )

        if not sheet_ids:
            return {
                'sheets'      : [],
                'hourly_mean' : {},
                'hourly_std'  : {},
                'avg_total'   : 0,
                'std_total'   : 0,
                'close_hour'  : DEFAULT_CLOSE_HOUR,
            }

        snapshots = HourlySheetSnapshot.objects.filter(
            daily_sheet__in = sheet_ids,
            branch          = self.branch,
            weekday         = weekday,
        ).values('daily_sheet', 'hour', 'job_count', 'revenue', 'date')

        # Group by sheet
        sheet_data = defaultdict(lambda: {'hourly_jobs': {}, 'hourly_rev': {}, 'total': 0, 'revenue': 0.0, 'date': None})
        for row in snapshots:
            sid = row['daily_sheet']
            sheet_data[sid]['hourly_jobs'][row['hour']] = row['job_count']
            sheet_data[sid]['hourly_rev'][row['hour']]  = float(row['revenue'] or 0)
            sheet_data[sid]['total']   += row['job_count']
            sheet_data[sid]['revenue'] += float(row['revenue'] or 0)
            sheet_data[sid]['date']     = row['date']

        sheets = [
            {
                'id'         : sid,
                'date'       : d['date'],
                'total'      : d['total'],
                'revenue'    : d['revenue'],
                'hourly_jobs': d['hourly_jobs'],
                'hourly_rev' : d['hourly_rev'],
            }
            for sid, d in sheet_data.items()
            if d['total'] > 0
        ]

        if not sheets:
            return {
                'sheets': [], 'hourly_mean': {}, 'hourly_std': {},
                'avg_total': 0, 'std_total': 0, 'close_hour': DEFAULT_CLOSE_HOUR,
            }

        # Mean and std dev per hour slot
        hour_job_lists = defaultdict(list)
        hour_rev_lists = defaultdict(list)
        for s in sheets:
            for hour in range(7, 20):
                hour_job_lists[hour].append(s['hourly_jobs'].get(hour, 0))
                hour_rev_lists[hour].append(s['hourly_rev'].get(hour, 0.0))

        hourly_mean = {h: sum(v) / len(v) for h, v in hour_job_lists.items()}
        hourly_std  = {
            h: math.sqrt(sum((x - hourly_mean[h]) ** 2 for x in v) / len(v))
            for h, v in hour_job_lists.items()
        }
        hourly_rev_mean = {h: sum(v) / len(v) for h, v in hour_rev_lists.items()}
        hourly_rev_std  = {
            h: math.sqrt(sum((x - hourly_rev_mean[h]) ** 2 for x in v) / len(v))
            for h, v in hour_rev_lists.items()
        }

        totals  = [s['total']   for s in sheets]
        revenues = [s['revenue'] for s in sheets]
        avg_total   = sum(totals)   / len(totals)
        avg_revenue = sum(revenues) / len(revenues)
        std_total   = math.sqrt(sum((t - avg_total)   ** 2 for t in totals)   / len(totals))
        std_revenue = math.sqrt(sum((r - avg_revenue) ** 2 for r in revenues) / len(revenues))

        # Close hour — average last active hour
        close_hours = [max(s['hourly_jobs'].keys()) for s in sheets if s['hourly_jobs']]
        close_hour  = int(sum(close_hours) / len(close_hours)) if close_hours else DEFAULT_CLOSE_HOUR

        return {
            'sheets'         : sheets,
            'hourly_mean'    : hourly_mean,
            'hourly_std'     : hourly_std,
            'hourly_rev_mean': hourly_rev_mean,
            'hourly_rev_std' : hourly_rev_std,
            'avg_total'      : avg_total,
            'std_total'      : std_total,
            'avg_revenue'    : avg_revenue,
            'std_revenue'    : std_revenue,
            'close_hour'     : close_hour,
        }

    # ── Week-of-month adjustment ──────────────────────────────────────────────

    def _week_of_month_factor(self, weekday: int, week_of_month: int) -> float:
        """
        Returns a multiplier based on historical performance in this
        week-of-month for this weekday. Falls back to 1.0 if insufficient data.
        """
        try:
            from apps.analytics.models import HourlySheetSnapshot
            from django.db.models import Sum

            sheets_this_week = HourlySheetSnapshot.objects.filter(
                branch        = self.branch,
                weekday       = weekday,
                week_of_month = week_of_month,
            ).values('daily_sheet').annotate(
                total=Sum('job_count')
            )

            sheets_all = HourlySheetSnapshot.objects.filter(
                branch  = self.branch,
                weekday = weekday,
            ).values('daily_sheet').annotate(
                total=Sum('job_count')
            )

            totals_this_week = [r['total'] for r in sheets_this_week if r['total'] > 0]
            totals_all       = [r['total'] for r in sheets_all if r['total'] > 0]

            if not totals_this_week or not totals_all:
                return 1.0

            avg_this_week = sum(totals_this_week) / len(totals_this_week)
            avg_all       = sum(totals_all)       / len(totals_all)

            if avg_all == 0:
                return 1.0

            factor = avg_this_week / avg_all
            return max(0.5, min(1.5, factor))  # cap at ±50%

        except Exception:
            return 1.0

    # ── Weather ───────────────────────────────────────────────────────────────

    def _get_weather_factor(self, date, current_hour: float) -> dict:
        """
        Fetches today's forecast from Open-Meteo and returns a discount
        factor for remaining hours. Clear=1.0, heavy rain=0.65.
        """
        try:
            import urllib.request
            import json
            from django.utils import timezone

            lat = float(self.branch.latitude)  if self.branch.latitude  else ACCRA_LAT
            lng = float(self.branch.longitude) if self.branch.longitude else ACCRA_LNG

            date_str = date.strftime('%Y-%m-%d')
            url = (
                f'https://api.open-meteo.com/v1/forecast'
                f'?latitude={lat}&longitude={lng}'
                f'&hourly=precipitation_probability,weathercode,precipitation'
                f'&start_date={date_str}&end_date={date_str}'
                f'&timezone=Africa%2FAccra'
            )

            with urllib.request.urlopen(url, timeout=4) as resp:
                data = json.loads(resp.read())

            hours     = data['hourly']['time']
            precip_p  = data['hourly']['precipitation_probability']
            precip    = data['hourly']['precipitation']
            wcodes    = data['hourly']['weathercode']

            # Only look at remaining hours
            remaining_hours = [
                (int(t[11:13]), precip_p[i], precip[i], wcodes[i])
                for i, t in enumerate(hours)
                if int(t[11:13]) > int(current_hour)
            ]

            if not remaining_hours:
                return {'factor': 1.0, 'note': ''}

            # Weighted average precipitation probability for remaining hours
            avg_precip_p = sum(h[1] or 0 for h in remaining_hours) / len(remaining_hours)
            max_precip   = max(h[2] or 0 for h in remaining_hours)

            if max_precip >= 5.0 or avg_precip_p >= 70:
                return {'factor': 0.65, 'note': 'Heavy rain forecast — significant footfall reduction expected'}
            elif max_precip >= 0.5 or avg_precip_p >= 40:
                return {'factor': 0.85, 'note': 'Light rain forecast — moderate footfall reduction expected'}
            elif any(w in range(71, 78) for _, _, _, w in remaining_hours):
                return {'factor': 0.90, 'note': 'Harmattan/dust conditions — mild footfall reduction expected'}
            elif avg_precip_p >= 20:
                return {'factor': 0.95, 'note': 'Chance of rain — slight footfall reduction possible'}
            else:
                return {'factor': 1.0, 'note': ''}

        except Exception as e:
            logger.debug('_get_weather_factor failed: %s', e)
            return {'factor': 1.0, 'note': ''}

    # ── Curve prediction ──────────────────────────────────────────────────────

    def _curve_predict(
        self,
        current_jobs    : int,
        current_revenue : float,
        avg_job_value   : float,
        current_hour    : float,
        history         : dict,
        week_of_month   : int,
        weather         : dict,
    ) -> dict:

        hourly_mean = history['hourly_mean']
        hourly_std  = history['hourly_std']
        avg_total   = history['avg_total']
        std_total   = history['std_total']
        avg_revenue = history['avg_revenue']
        std_revenue = history['std_revenue']
        close_hour  = history['close_hour']
        weekday     = history['sheets'][0]['date'].weekday() if history['sheets'] else 0

        # ── Deviation factor ──────────────────────────────────
        expected_so_far = sum(
            hourly_mean.get(h, 0)
            for h in range(7, int(current_hour) + 1)
        )
        if expected_so_far > 1.0:
            deviation_factor = current_jobs / expected_so_far
            deviation_factor = max(0.3, min(2.0, deviation_factor))
        else:
            deviation_factor = 1.0

        # ── Week-of-month factor ──────────────────────────────
        wom_factor = self._week_of_month_factor(weekday, week_of_month)

        # Blend: 80% weekday baseline deviation + 20% week-of-month
        blended_factor = (
            deviation_factor * (1 - WEEK_OF_MONTH_WEIGHT) +
            wom_factor       * WEEK_OF_MONTH_WEIGHT
        )

        # ── Remaining jobs projection ─────────────────────────
        remaining_mean = sum(
            hourly_mean.get(h, 0)
            for h in range(int(current_hour) + 1, close_hour + 1)
        )
        remaining_std = math.sqrt(sum(
            (hourly_std.get(h, 0)) ** 2
            for h in range(int(current_hour) + 1, close_hour + 1)
        ))

        # Apply blended factor and weather to remaining
        projected_remaining       = remaining_mean * blended_factor * weather['factor']
        projected_remaining_low   = max(0, (remaining_mean - remaining_std) * blended_factor * weather['factor'])
        projected_remaining_high  = (remaining_mean + remaining_std) * blended_factor

        # ── Point estimates ───────────────────────────────────
        jobs_point   = round(current_jobs + projected_remaining)
        jobs_low     = round(current_jobs + projected_remaining_low)
        jobs_high    = round(current_jobs + projected_remaining_high)

        # ── Revenue bounds ────────────────────────────────────
        # Use today's avg job value if we have enough data, else historical
        if current_jobs >= 3:
            rev_per_job = avg_job_value
        else:
            rev_per_job = avg_revenue / avg_total if avg_total > 0 else avg_job_value

        revenue_point = round(current_revenue + projected_remaining * rev_per_job, 2)
        revenue_low   = round(current_revenue + projected_remaining_low  * rev_per_job, 2)
        revenue_high  = round(current_revenue + projected_remaining_high * rev_per_job, 2)

        # ── Confidence ────────────────────────────────────────
        operating_hours = max(close_hour - DEFAULT_OPEN_HOUR, 1)
        hours_elapsed   = max(current_hour - DEFAULT_OPEN_HOUR, 0)
        elapsed_pct     = min(hours_elapsed / operating_hours, 1.0)

        # Base confidence from elapsed time
        confidence = 15 + int(elapsed_pct * 65)  # 15% at open → 80% near close

        # Bonus: more historical data = more confidence
        data_weeks = len(history['sheets'])
        confidence += min(data_weeks, 10)  # up to +10 for 10+ weeks of data

        # Bonus: today's pace close to historical norm = predictable day
        if 0.85 <= deviation_factor <= 1.15:
            confidence += 5  # normal day bonus

        # Penalty: weather uncertainty
        if weather['factor'] < 0.85:
            confidence -= 8
        elif weather['factor'] < 1.0:
            confidence -= 3

        # Penalty: high deviation from norm = unpredictable
        if deviation_factor > 1.5 or deviation_factor < 0.6:
            confidence -= 5

        confidence = max(10, min(94, confidence))

        remaining_hours = max(close_hour - current_hour, 0)

        # ── Credit signal ─────────────────────────────────────────
        credit = self._credit_signal(None, current_hour)
        revenue_low   = revenue_low   + credit['contribution'] * 0.5
        revenue_point = revenue_point + credit['contribution']
        revenue_high  = revenue_high  + credit['contribution'] * 1.5

        return {
            'jobs_low'        : max(current_jobs, jobs_low),
            'jobs_high'       : jobs_high,
            'jobs_point'      : max(current_jobs, jobs_point),
            'revenue_low'     : max(current_revenue, round(revenue_low, 2)),
            'revenue_high'    : round(revenue_high, 2),
            'revenue_point'   : max(current_revenue, round(revenue_point, 2)),
            'confidence_pct'  : confidence,
            'method'          : 'curve',
            'remaining_hours' : round(remaining_hours, 1),
            'close_hour'      : close_hour,
            'weather_factor'  : weather['factor'],
            'weather_note'    : weather['note'],
            'deviation_factor': round(deviation_factor, 2),
            'data_weeks'      : data_weeks,
            'credit_signal'   : credit,
        }

    # ── Credit signal ─────────────────────────────────────────────────────────

    def _credit_signal(self, sheet, current_hour: float) -> dict:
        """
        Estimates additional revenue likely from credit settlements today.
        Adaptively weighted by payment history volume — low data = low weight.

        Returns:
            {
                'contribution'  : float  — expected additional revenue
                'weight'        : float  — 0.0–0.25 adaptive weight applied
                'outstanding'   : float  — total outstanding balance
                'accounts'      : int    — active accounts with balance
                'data_points'   : int    — total settlement records available
            }
        """
        try:
            from apps.finance.models import CreditAccount, CreditPayment
            from django.db.models import Sum, Count
            from django.utils import timezone

            today   = timezone.localdate()
            weekday = today.weekday()  # 0=Mon, 6=Sun

            # ── Outstanding balances ──────────────────────────────
            accounts = CreditAccount.objects.filter(
                branch  = self.branch,
                status  = 'ACTIVE',
            ).exclude(current_balance__lte=0)

            outstanding = float(
                accounts.aggregate(t=Sum('current_balance'))['t'] or 0
            )
            account_count = accounts.count()

            if outstanding <= 0 or account_count == 0:
                return {
                    'contribution': 0.0, 'weight': 0.0,
                    'outstanding': 0.0, 'accounts': 0, 'data_points': 0,
                }

            # ── Settlement history for this branch ────────────────
            all_payments = CreditPayment.objects.filter(
                credit_account__branch=self.branch,
            )
            total_payments = all_payments.count()

            # Adaptive weight — needs 10+ records for full signal
            weight = min(total_payments / 10.0, 1.0) * 0.25
            if weight < 0.01:
                return {
                    'contribution': 0.0, 'weight': 0.0,
                    'outstanding': outstanding,
                    'accounts': account_count,
                    'data_points': total_payments,
                }

            # ── P(settles today | weekday) ────────────────────────
            # What fraction of historical settlements happened on this weekday?
            weekday_payments = all_payments.filter(
                created_at__week_day=(weekday + 2) % 7 or 7
            ).count()

            if total_payments > 0:
                p_weekday = weekday_payments / total_payments
            else:
                p_weekday = 1 / 6  # uniform prior across 6 working days

            # ── Already settled today — don't double count ─────────
            settled_today = float(
                all_payments.filter(
                    created_at__date=today
                ).aggregate(t=Sum('amount'))['t'] or 0
            )

            # ── Recency factor per account ────────────────────────
            # Accounts approaching payment terms = higher probability
            recency_boost = 1.0
            try:
                for account in accounts.select_related('customer')[:10]:
                    last = CreditPayment.objects.filter(
                        credit_account=account
                    ).order_by('-created_at').first()

                    if last:
                        days_since = (today - last.created_at.date()).days
                        terms = account.payment_terms or 30
                        # Boost if approaching due date
                        if days_since >= terms * 0.8:
                            recency_boost = min(recency_boost * 1.2, 2.0)
                        # Discount if settled very recently
                        elif days_since <= 2:
                            recency_boost = max(recency_boost * 0.5, 0.1)
            except Exception:
                recency_boost = 1.0

            # ── Hours remaining factor ────────────────────────────
            # Less likely to settle in last hour vs peak business hours
            hours_remaining = max(DEFAULT_CLOSE_HOUR - current_hour, 0)
            time_factor = min(hours_remaining / 8.0, 1.0)

            # ── Final contribution ────────────────────────────────
            remaining_outstanding = max(outstanding - settled_today, 0)
            p_settle = p_weekday * recency_boost * time_factor
            p_settle = max(0.0, min(p_settle, 0.8))  # cap at 80%

            contribution = remaining_outstanding * p_settle * weight

            return {
                'contribution': round(contribution, 2),
                'weight'      : round(weight, 3),
                'outstanding' : round(outstanding, 2),
                'accounts'    : account_count,
                'data_points' : total_payments,
                'p_settle'    : round(p_settle, 3),
                'settled_today': round(settled_today, 2),
            }

        except Exception as e:
            logger.warning('_credit_signal failed: %s', e)
            return {
                'contribution': 0.0, 'weight': 0.0,
                'outstanding': 0.0, 'accounts': 0, 'data_points': 0,
            }

    # ── Linear fallback ───────────────────────────────────────────────────────

    def _linear_predict(
        self,
        current_jobs    : int,
        current_revenue : float,
        avg_job_value   : float,
        current_hour    : float,
        close_hour      : int,
    ) -> dict:

        hours_elapsed   = max(current_hour - DEFAULT_OPEN_HOUR, 0.25)
        hours_remaining = max(close_hour - current_hour, 0)
        jobs_per_hour   = current_jobs / hours_elapsed if hours_elapsed > 0 else 0
        rev_per_hour    = current_revenue / hours_elapsed if hours_elapsed > 0 else 0

        projected_remaining = jobs_per_hour * hours_remaining

        # Simple bounds: ±30% on linear projection
        jobs_point   = round(current_jobs + projected_remaining)
        jobs_low     = round(current_jobs + projected_remaining * 0.7)
        jobs_high    = round(current_jobs + projected_remaining * 1.3)

        revenue_point = round(current_revenue + rev_per_hour * hours_remaining, 2)
        revenue_low   = round(revenue_point * 0.7, 2)
        revenue_high  = round(revenue_point * 1.3, 2)

        operating_hours = max(close_hour - DEFAULT_OPEN_HOUR, 1)
        confidence      = max(10, min(45, int(15 + (min(hours_elapsed / operating_hours, 1.0) * 30))))

        credit = self._credit_signal(None, current_hour)
        revenue_low   = revenue_low   + credit['contribution'] * 0.5
        revenue_point = revenue_point + credit['contribution']
        revenue_high  = revenue_high  + credit['contribution'] * 1.5

        return {
            'jobs_low'        : max(current_jobs, jobs_low),
            'jobs_high'       : jobs_high,
            'jobs_point'      : max(current_jobs, jobs_point),
            'revenue_low'     : max(current_revenue, round(revenue_low, 2)),
            'revenue_high'    : round(revenue_high, 2),
            'revenue_point'   : max(current_revenue, round(revenue_point, 2)),
            'confidence_pct'  : confidence,
            'method'          : 'linear_fallback',
            'remaining_hours' : round(hours_remaining, 1),
            'close_hour'      : close_hour,
            'weather_factor'  : 1.0,
            'weather_note'    : '',
            'deviation_factor': 1.0,
            'data_weeks'      : 0,
            'credit_signal'   : credit,
        }