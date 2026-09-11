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
def recovery_float_check():
    """
    Runs at 4pm daily. Creates a recovery float for any open sheet
    that has no float record yet — handles disrupted/delayed-start days
    so the cashier can always sign off normally.
    """
    from django.core.management import call_command
    call_command('recovery_float_check')


@shared_task
def prepare_weekly_filings():
    """
    Saturday evening. Builds the draft so the figures are waiting when the
    manager opens the page; submitting stays a person's act.

    A convenience, not the guarantee — the portal prepares the week itself
    on Monday if this never ran.
    """
    from django.core.management import call_command
    call_command('prepare_weekly_filings')


@shared_task
def expire_wallet_credits():
    """
    Runs once daily. Zeroes out wallet balances inactive for 6+ months,
    writing an EXPIRED CustomerWalletTransaction entry for each — never
    a silent deletion.
    """
    from django.core.management import call_command
    call_command('expire_wallet_credits')