# apps/notifications/apps.py
from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'apps.notifications'
    label = 'notifications'

    def ready(self):
        from apps.notifications.signals import connect_all
        connect_all()