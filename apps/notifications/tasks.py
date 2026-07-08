from celery import shared_task


@shared_task
def generate_shift_reminders():
    from django.core.management import call_command
    call_command('generate_reminders', '--type', 'shift')


@shared_task
def generate_checkpoint_reminders():
    from django.core.management import call_command
    call_command('generate_reminders', '--type', 'checkpoint')