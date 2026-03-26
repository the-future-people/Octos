from celery import shared_task

@shared_task
def open_sheets():
    from django.core.management import call_command
    call_command('run_sheet_tasks', 'open')

@shared_task
def close_sheets():
    from django.core.management import call_command
    call_command('run_sheet_tasks', 'close')

@shared_task
def warn_sheets():
    from django.core.management import call_command
    call_command('run_sheet_tasks', 'warn')

@shared_task
def suspend_overdue():
    from django.core.management import call_command
    call_command('run_sheet_tasks', 'suspend')

@shared_task
def check_credit_due():
    from django.core.management import call_command
    call_command('check_credit_due')

@shared_task
def check_credit_due():
    from django.core.management import call_command
    call_command('check_credit_due')