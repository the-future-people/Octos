"""
Management command: backfill_hourly_snapshots
=============================================
Populates HourlySheetSnapshot for all closed sheets that don't
already have snapshots. Runs once — safe to re-run (skips existing).

Usage:
    python manage.py backfill_hourly_snapshots
    python manage.py backfill_hourly_snapshots --branch WLB
    python manage.py backfill_hourly_snapshots --dry-run
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Backfill HourlySheetSnapshot for all closed sheets'

    def add_arguments(self, parser):
        parser.add_argument(
            '--branch',
            type=str,
            default=None,
            help='Branch code to backfill (default: all branches)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without writing to DB',
        )

    def handle(self, *args, **options):
        from apps.finance.models import DailySalesSheet
        from apps.analytics.models import HourlySheetSnapshot
        from apps.jobs.models import Job
        from django.db.models import Count, Sum
        from django.db.models.functions import ExtractHour
        from collections import defaultdict
        import urllib.request
        import json

        branch_code = options['branch']
        dry_run     = options['dry_run']

        # ── Fetch closed sheets ───────────────────────────────
        qs = DailySalesSheet.objects.exclude(
            status=DailySalesSheet.Status.OPEN,
        ).select_related('branch').order_by('date')

        if branch_code:
            qs = qs.filter(branch__code=branch_code)

        total_sheets = qs.count()
        self.stdout.write(
            self.style.NOTICE(
                f'Found {total_sheets} closed sheets'
                + (f' for branch {branch_code}' if branch_code else '')
                + (' [DRY RUN]' if dry_run else '')
            )
        )

        # ── Skip sheets already snapshotted ──────────────────
        already_done = set(
            HourlySheetSnapshot.objects.values_list('daily_sheet_id', flat=True).distinct()
        )
        sheets_to_process = [s for s in qs if s.pk not in already_done]

        self.stdout.write(
            f'{len(already_done)} already snapshotted — '
            f'{len(sheets_to_process)} to process'
        )

        if not sheets_to_process:
            self.stdout.write(self.style.SUCCESS('Nothing to do.'))
            return

        created_total = 0
        skipped       = 0

        for sheet in sheets_to_process:
            branch = sheet.branch

            # Week of month
            day           = sheet.date.day
            week_of_month = (day - 1) // 7 + 1

            # Hourly job counts and revenue
            hourly_qs = Job.objects.filter(
                daily_sheet = sheet,
                status      = 'COMPLETE',
            ).annotate(
                hour = ExtractHour('created_at'),
            ).values('hour').annotate(
                job_count = Count('id'),
                revenue   = Sum('amount_paid'),
            ).order_by('hour')

            hourly_data = {
                row['hour']: {
                    'job_count': row['job_count'],
                    'revenue':   float(row['revenue'] or 0),
                }
                for row in hourly_qs
            }

            # Fetch historical weather from Open-Meteo archive
            weather_by_hour = self._fetch_weather(
                lat  = float(branch.latitude)  if branch.latitude  else 5.6037,
                lng  = float(branch.longitude) if branch.longitude else -0.1870,
                date = sheet.date,
            )

            # Build snapshot records
            snapshots = []
            for hour in range(7, 20):
                data      = hourly_data.get(hour, {'job_count': 0, 'revenue': 0.0})
                job_count = data['job_count']
                revenue   = data['revenue']
                avg_val   = round(revenue / job_count, 2) if job_count > 0 else 0.0
                weather   = weather_by_hour.get(hour, {})

                snapshots.append(HourlySheetSnapshot(
                    daily_sheet       = sheet,
                    branch            = branch,
                    date              = sheet.date,
                    weekday           = sheet.date.weekday(),
                    week_of_month     = week_of_month,
                    hour              = hour,
                    job_count         = job_count,
                    revenue           = revenue,
                    avg_job_value     = avg_val,
                    weather_condition = weather.get('condition', ''),
                    precipitation_mm  = weather.get('precipitation_mm', 0),
                ))

            if dry_run:
                self.stdout.write(
                    f'  [DRY RUN] {sheet.branch.code} {sheet.date} — '
                    f'would create {len(snapshots)} snapshots '
                    f'({sum(h["job_count"] for h in hourly_data.values())} jobs)'
                )
                created_total += len(snapshots)
                continue

            HourlySheetSnapshot.objects.bulk_create(
                snapshots, ignore_conflicts=True
            )
            created_total += len(snapshots)

            self.stdout.write(
                f'  ✓ {sheet.branch.code} {sheet.date} — '
                f'{len(snapshots)} slots '
                f'({sum(h["job_count"] for h in hourly_data.values())} jobs)'
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"[DRY run] Would create" if dry_run else "Created"} '
                f'{created_total} HourlySheetSnapshot records '
                f'across {len(sheets_to_process)} sheets.'
            )
        )

    def _fetch_weather(self, lat: float, lng: float, date) -> dict:
        """
        Fetch hourly precipitation from Open-Meteo archive for a past date.
        Returns {hour: {condition, precipitation_mm}} or {} on failure.
        """
        try:
            import urllib.request
            import json
            date_str = date.strftime('%Y-%m-%d')
            url = (
                f'https://archive-api.open-meteo.com/v1/archive'
                f'?latitude={lat}&longitude={lng}'
                f'&start_date={date_str}&end_date={date_str}'
                f'&hourly=precipitation,weathercode'
                f'&timezone=Africa%2FAccra'
            )
            with urllib.request.urlopen(url, timeout=6) as resp:
                data = json.loads(resp.read())

            hours    = data['hourly']['time']
            precip   = data['hourly']['precipitation']
            wcodes   = data['hourly']['weathercode']

            def _condition(code, p):
                if p >= 5.0:              return 'heavy_rain'
                if p >= 0.5:              return 'light_rain'
                if code in range(51, 68): return 'light_rain'
                if code in range(71, 78): return 'harmattan'
                if code in range(1, 4):   return 'cloudy'
                return 'clear'

            result = {}
            for i, t in enumerate(hours):
                hour = int(t[11:13])
                if 7 <= hour <= 19:
                    p = float(precip[i] or 0)
                    result[hour] = {
                        'condition'       : _condition(wcodes[i], p),
                        'precipitation_mm': round(p, 2),
                    }
            return result

        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f'    Weather fetch failed for {date}: {e}')
            )
            return {}