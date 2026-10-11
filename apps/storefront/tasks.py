from celery import shared_task


@shared_task
def sweep_storefront():
    """
    Nightly. Removes expired carts and artwork nobody committed.

    A thin wrapper, like the sheet tasks: the work lives in a command
    so it can be run by hand when something needs clearing before the
    night comes round.
    """
    from django.core.management import call_command
    call_command('sweep_storefront')