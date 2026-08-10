from apps.analytics.tasks.daily import analyse_daily_risk
from apps.analytics.tasks.weekly import compute_weekly_risk
from apps.analytics.tasks.monthly import compile_monthly_summary
from apps.analytics.tasks.weather import refresh_weather_cache

# Every task in this package must be imported above. Celery's autodiscovery
# imports apps.analytics.tasks and registers only what this module exposes —
# a task left out is scheduled by beat, received by the worker, and discarded
# as unregistered, with nothing surfacing as an error.
__all__ = [
    'analyse_daily_risk',
    'compute_weekly_risk',
    'compile_monthly_summary',
    'refresh_weather_cache',
]