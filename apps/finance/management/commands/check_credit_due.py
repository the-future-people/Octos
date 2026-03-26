"""
check_credit_due — Daily credit account health check

Runs every morning. For each active credit account:
1. If balance > 0 and payment_terms days have elapsed since last job → notify customer + BM
2. If balance > 0 and 2× payment_terms have elapsed → suspend account + notify BM
3. If balance == 0 and account was suspended → reactivate (handled by CreditEngine.settle)

Notification channels:
- In-app notification to BM (always)
- WhatsApp message to customer (if phone on file) — stubbed until WA API wired
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Check overdue credit accounts and send notifications.'

    def handle(self, *args, **options):
        from apps.finance.models import CreditAccount
        from apps.jobs.models import Job
        from apps.notifications.services import notify

        now      = timezone.now()
        checked  = 0
        notified = 0
        suspended = 0

        active_accounts = CreditAccount.objects.filter(
            status='ACTIVE',
            current_balance__gt=0,
        ).select_related('customer', 'branch', 'nominated_by')

        for account in active_accounts:
            checked += 1

            # Find the most recent completed credit job on this account
            last_job = Job.objects.filter(
                credit_account = account,
                status         = 'COMPLETE',
            ).order_by('-created_at').first()

            if not last_job:
                continue

            days_since = (now - last_job.created_at).days
            terms      = account.payment_terms  # e.g. 30 days

            # ── Hard suspension: 2× terms elapsed ────────────────
            if days_since >= terms * 2:
                account.status            = 'SUSPENDED'
                account.suspended_at      = now
                account.suspension_reason = (
                    f'Auto-suspended: balance of GHS {account.current_balance} '
                    f'overdue by {days_since} days (terms: {terms} days).'
                )
                account.save(update_fields=[
                    'status', 'suspended_at', 'suspension_reason', 'updated_at'
                ])
                suspended += 1

                # Notify BM
                if account.nominated_by:
                    notify(
                        recipient = account.nominated_by,
                        message   = (
                            f"⚠ Credit account for {account.customer.display_name} "
                            f"has been AUTO-SUSPENDED. "
                            f"Outstanding: GHS {account.current_balance}. "
                            f"Overdue by {days_since} days."
                        ),
                        category  = 'CREDIT',
                    )

                # TODO: Send WhatsApp to customer when WA API is wired
                self.stdout.write(
                    self.style.WARNING(
                        f'SUSPENDED: {account.customer.display_name} — '
                        f'GHS {account.current_balance} — {days_since} days overdue'
                    )
                )

            # ── Reminder: terms elapsed but not yet at 2× ────────
            elif days_since >= terms:
                notified += 1

                # Notify BM
                if account.nominated_by:
                    notify(
                        recipient = account.nominated_by,
                        message   = (
                            f"{account.customer.display_name}'s credit balance of "
                            f"GHS {account.current_balance} is overdue "
                            f"({days_since} days, terms: {terms} days). "
                            f"Please follow up."
                        ),
                        category  = 'CREDIT',
                    )

                # TODO: Send WhatsApp to customer when WA API is wired
                # Message would be:
                # "Dear {name}, your outstanding balance of GHS {amount} at
                #  Farhat {branch} is due. Please visit us to settle.
                #  Thank you."
                self.stdout.write(
                    self.style.NOTICE(
                        f'OVERDUE: {account.customer.display_name} — '
                        f'GHS {account.current_balance} — {days_since} days'
                    )
                )

        # ── Also check suspended accounts with CreditPayment ─────
        # If a suspended account has been fully settled via CreditEngine,
        # CreditEngine.settle() already reactivates it — nothing to do here.

        self.stdout.write(
            self.style.SUCCESS(
                f'check_credit_due complete — '
                f'checked: {checked}, notified: {notified}, suspended: {suspended}'
            )
        )