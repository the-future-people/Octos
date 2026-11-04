import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
app = Celery('octos')
app.config_from_object('django.conf:settings', namespace='CELERY')
# Explicit list rather than the default INSTALLED_APPS scan: an app missing
# here has its tasks silently discarded by the worker at runtime — beat
# schedules them by name, the worker finds nothing registered, and the
# message is dropped with no failure anywhere that a person would see.
# Every app in INSTALLED_APPS, found by Celery itself. The explicit list
# that was here forgot apps.storefront (lessons, 13 Oct) and then
# apps.communications (4 Nov); a list nobody has to maintain can't forget.
app.autodiscover_tasks()