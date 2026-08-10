import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
app = Celery('octos')
app.config_from_object('django.conf:settings', namespace='CELERY')
# Explicit list rather than the default INSTALLED_APPS scan: an app missing
# here has its tasks silently discarded by the worker at runtime — beat
# schedules them by name, the worker finds nothing registered, and the
# message is dropped with no failure anywhere that a person would see.
app.autodiscover_tasks([
    'apps.finance',
    'apps.jobs',
    'apps.analytics',
    'apps.notifications',
])