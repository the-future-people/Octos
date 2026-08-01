"""
Management command: recovery_float_check
=========================================
Runs at 4pm daily via Celery beat.

For every open sheet that has no CashierFloat record, creates a
recovery float automatically so the cashier can sign off normally.

This handles disrupted or delayed-start days where the normal BM
float-staging flow was never completed (power outage, flooding, etc.).

The created float is flagged with is_recovery_float=True so it's
clearly distinguishable from a normally-staged float in audit logs
and reports.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Create recovery floats for open sheets with no float record'

    def handle(self, *args, **options):
        from apps.finance.models import DailySalesSheet, CashierFloat
        from apps.accounts.models import CustomUser

        now   = timezone.now()
        today = timezone.localdate()

        # Only process today's open sheets
        open_sheets = DailySalesSheet.objects.filter(
            date   = today,
            status = DailySalesSheet.Status.OPEN,
        ).select_related('branch')

        if not open_sheets.exists():
            self.stdout.write('No open sheets found for today.')
            return

        created_count = 0

        for sheet in open_sheets:
            # Skip if float already exists
            if CashierFloat.objects.filter(daily_sheet=sheet).exists():
                self.stdout.write(
                    f'  {sheet.branch.code} {sheet.date} — float exists, skipping'
                )
                continue

            # Find the active cashier for this branch
            cashier_user = CustomUser.objects.filter(
                branch     = sheet.branch,
                role__name = 'CASHIER',
                is_active  = True,
            ).first()

            if not cashier_user:
                self.stdout.write(
                    self.style.WARNING(
                        f'  {sheet.branch.code} {sheet.date} — no cashier found, skipping'
                    )
                )
                continue

            # Create recovery float.
            #
            # opening_float uses the branch standard rather than 0: the
            # cashier physically holds a float regardless of whether the
            # system recorded one, and expected_cash is computed as
            # opening_float + cash_collected - petty_cash_out. Recording 0
            # here would understate expected cash and show the cashier as
            # holding a surplus she never received.
            #
            # float_set_by stays None — no human staged this float, and
            # attributing it to the cashier would contradict the rule that
            # a cashier never sets their own float.
            from apps.finance.sheet_engine import SheetEngine

            CashierFloat.objects.create(
                daily_sheet             = sheet,
                cashier                 = cashier_user,
                float_set_by            = None,
                opening_float           = SheetEngine.DEFAULT_FLOAT_AMOUNT,
                scheduled_date          = today,
                morning_acknowledged    = True,
                morning_acknowledged_at = now,
                is_recovery_float       = True,
                shift_notes             = (
                    f'Recovery float auto-created at {now.strftime("%H:%M")} '
                    f'by system — no float was staged for this shift. '
                    f'Opening float assumed to be the branch standard; '
                    f'BM should verify against the physical count. '
                    f'Branch may have experienced a delayed start or disruption.'
                ),
            )
            created_count += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f'  ✓ {sheet.branch.code} {sheet.date} — recovery float created for {cashier_user.full_name}'
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone — {created_count} recovery float(s) created.'
            )
        )