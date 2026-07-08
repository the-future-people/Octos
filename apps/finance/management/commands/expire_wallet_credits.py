import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

EXPIRY_MONTHS = 6


class Command(BaseCommand):
    """
    Zeroes out wallet balances that have had no activity (add or
    redeem) for 6+ months. Never a silent deletion — every expiry
    writes an EXPIRED CustomerWalletTransaction entry, preserving
    the full audit trail per the original design requirement.

    Usage:
        python manage.py expire_wallet_credits
    """

    help = 'Expire customer wallet balances inactive for 6+ months'

    def handle(self, *args, **options):
        from apps.customers.models import CustomerProfile
        from apps.finance.models import CustomerWalletTransaction

        cutoff = timezone.now() - timedelta(days=EXPIRY_MONTHS * 30)

        stale_customers = CustomerProfile.objects.filter(
            wallet_balance__gt=0,
            wallet_last_activity_at__lt=cutoff,
        )

        expired_count = 0
        for customer in stale_customers:
            with transaction.atomic():
                # Re-fetch under lock — balance may have changed
                # between the queryset evaluation above and now.
                locked = CustomerProfile.objects.select_for_update().get(pk=customer.pk)
                if locked.wallet_balance <= 0:
                    continue
                if locked.wallet_last_activity_at and locked.wallet_last_activity_at >= cutoff:
                    continue  # activity happened since the queryset ran

                balance_before = locked.wallet_balance

                CustomerWalletTransaction.objects.create(
                    customer         = locked,
                    branch           = locked.branch or locked.preferred_branch,
                    job              = None,  # only case where job is legitimately null
                    transaction_type = CustomerWalletTransaction.TransactionType.EXPIRED,
                    amount           = balance_before,
                    balance_before   = balance_before,
                    balance_after    = 0,
                    recorded_by      = None,
                )

                CustomerProfile.objects.filter(pk=locked.pk).update(
                    wallet_balance=0,
                )
                expired_count += 1

        self.stdout.write(self.style.SUCCESS(f'wallet expiry — {expired_count} customer(s) expired'))