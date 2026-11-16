from celery import shared_task


@shared_task
def alert_long_breaks():
    """Every five minutes: tell the Branch Manager about breaks past 30 minutes."""
    from apps.analytics.breaks import alert_long_breaks as run
    return run()
