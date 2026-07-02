from celery import shared_task


@shared_task
def refresh_weather_cache():
    from django.core.management import call_command
    call_command('refresh_weather_cache')