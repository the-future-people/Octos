"""
Management command: refresh_weather_cache
==========================================
Fetches current weather forecast for every branch with coordinates
set, and stores the result in Redis cache. Runs every 15 minutes via
Celery beat.

This exists so the prediction engine NEVER makes a live network call
during a user-facing request. Weather data is fetched here, in the
background, and the prediction engine only ever reads from cache.

Root cause this fixes: Open-Meteo DNS resolution was taking 40+
seconds from Railway's network, and the request-path timeout wasn't
being respected — every Day Sheet load across BM and cashier portals
was hanging on this call, causing system-wide slowness.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Fetch weather forecast for all branches and cache it'

    def handle(self, *args, **options):
        import urllib.request
        import json
        from django.core.cache import cache
        from apps.organization.models import Branch

        branches = Branch.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
            is_active=True,
        )

        if not branches.exists():
            self.stdout.write('No branches with coordinates set.')
            return

        for branch in branches:
            cache_key = f'weather_forecast:{branch.pk}'
            try:
                lat = float(branch.latitude)
                lng = float(branch.longitude)
                url = (
                    f'https://api.open-meteo.com/v1/forecast'
                    f'?latitude={lat}&longitude={lng}'
                    f'&hourly=precipitation_probability,weathercode,precipitation'
                    f'&timezone=Africa%2FAccra'
                )

                with urllib.request.urlopen(url, timeout=8) as resp:
                    data = json.loads(resp.read())

                cache.set(cache_key, data, 1200)  # 20 min TTL — outlives the 15 min refresh
                self.stdout.write(
                    self.style.SUCCESS(f'  ✓ {branch.code} — weather cached')
                )

            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f'  ✗ {branch.code} — fetch failed: {e}')
                )
                # Deliberately do NOT clear existing cache on failure —
                # stale weather data is better than no data, and the
                # prediction engine's fallback only kicks in if the
                # key is truly empty (e.g. first run ever).

        self.stdout.write(self.style.SUCCESS('Weather cache refresh complete.'))