from __future__ import annotations

import logging
from datetime import date, time, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class SheetEngine:
    """
    Controls the full lifecycle of a DailySalesSheet.

    Responsibilities:
    - Auto-open a sheet for a branch on a given date
    - Provide a fallback open if the scheduled task missed
    - Enforce the staged end-of-day close sequence
    - Handle the 10-minute payment extension when jobs are pending
    - Auto-close sheets that were never manually closed
    - Freeze and snapshot totals at close — numbers never change after

    Rules:
    - One sheet per branch per day — enforced at DB level
    - Sundays never open
    - Public holidays open but are flagged with name and date
    - Regular pending payments cannot carry over — BM must resolve
    - Credit account and cross-branch jobs are legitimate carryovers
    - Sheet is immutable once closed — no reopening ever
    """

    # ── Close sequence timings (minutes before/after closing_time) ──
    WARNING_BEFORE_CLOSE    = 30   # full screen warning modal
    ATTENDANT_LOCK_AT_CLOSE = 0    # no new jobs at closing_time
    CASHIER_LOCK_AFTER      = 30   # cashiers locked 30 min after closing_time
    BM_AUTOCLOSE_AFTER      = 60   # sheet auto-closes 60 min after closing_time
    PAYMENT_EXTENSION       = 10   # extra minutes granted when pending jobs exist

    def __init__(self, branch) -> None:
        self.branch = branch

    # ── Open ──────────────────────────────────────────────────────

    @transaction.atomic
    def open_sheet(
        self,
        target_date: Optional[date] = None,
        opened_by=None,
        holiday_name: str = '',
    ):
        """
        Open a daily sheet for the branch on the target date.
        If a sheet already exists for that date, return it unchanged.

        Args:
            target_date  : Date to open for — defaults to today
            opened_by    : CustomUser opening the sheet — None if system
            holiday_name : Public holiday name if applicable

        Returns:
            tuple(DailySalesSheet, created: bool)
        """
        from apps.finance.models import DailySalesSheet

        if target_date is None:
            target_date = timezone.localdate()

        # Never open on a Sunday
        if target_date.weekday() == 6:
            logger.info(
                'SheetEngine: skipping Sunday %s for branch %s',
                target_date,
                self.branch.code,
            )
            return None, False

        is_holiday = bool(holiday_name)

        sheet, created = DailySalesSheet.objects.get_or_create(
            branch=self.branch,
            date=target_date,
            defaults={
                'status'             : DailySalesSheet.Status.OPEN,
                'opened_by'          : opened_by,
                'is_public_holiday'  : is_holiday,
                'public_holiday_name': holiday_name,
            },
        )

        if created:
            logger.info(
                'SheetEngine: opened sheet %s for branch %s on %s',
                sheet.pk,
                self.branch.code,
                target_date,
            )

        return sheet, created

    def get_or_open_today(self, opened_by=None):
        """
        Fallback: get today's open sheet or create one on the spot.
        Called when the scheduled task may have missed.
        Never blocks an operation waiting for a sheet.
        On Sundays, returns existing sheet if present — never creates.
        """
        from apps.finance.models import DailySalesSheet
        today = timezone.localdate()

        # Always return existing sheet if one exists — regardless of day
        existing = DailySalesSheet.objects.filter(
            branch=self.branch,
            date=today,
        ).first()
        if existing:
            return existing, False

        # Sunday — don't auto-create, return None
        if today.weekday() == 6:
            return None, False

        return self.open_sheet(
            target_date=today,
            opened_by=opened_by,
        )
    # ── Close sequence ────────────────────────────────────────────

    def get_close_schedule(self) -> dict:
        """
        Returns the computed timestamps for today's close sequence
        based on the branch's closing_time.
        """
        today        = timezone.localdate()
        closing_time = self.branch.closing_time  # TimeField

        def _dt(t: time):
            from datetime import datetime
            naive = datetime.combine(today, t)
            return timezone.make_aware(naive)

        base = _dt(closing_time)

        return {
            'warning_at'       : base - timedelta(minutes=self.WARNING_BEFORE_CLOSE),
            'attendant_lock_at': base,
            'cashier_lock_at'  : base + timedelta(minutes=self.CASHIER_LOCK_AFTER),
            'bm_autoclose_at'  : base + timedelta(minutes=self.BM_AUTOCLOSE_AFTER),
        }

    def has_pending_payments(self, sheet) -> bool:
        """
        Check if the sheet has any jobs still in PENDING_PAYMENT
        that are not legitimate carryovers (credit or cross-branch).
        """
        from apps.jobs.models import Job

        return Job.objects.filter(
            daily_sheet=sheet,
            status=Job.PENDING_PAYMENT,
            is_routed=False,
            customer__credit_account__isnull=True,
        ).exists()

    def get_pending_payment_count(self, sheet) -> int:
        """Count of non-carryover pending payment jobs on this sheet."""
        from apps.jobs.models import Job

        return Job.objects.filter(
            daily_sheet=sheet,
            status=Job.PENDING_PAYMENT,
            is_routed=False,
            customer__credit_account__isnull=True,
        ).count()

    @transaction.atomic
    def close_sheet(
        self,
        sheet,
        closed_by=None,
        auto: bool = False,
    ):
        """
        Close a daily sheet and freeze all totals.

        Args:
            sheet     : DailySalesSheet instance to close
            closed_by : CustomUser closing the sheet — None if auto-close
            auto      : True if triggered by the scheduled task

        Returns:
            DailySalesSheet with frozen totals

        Raises:
            ValueError : Sheet is already closed
            ValueError : Non-carryover pending payments still exist
                         and extension window has also passed
        """
        from apps.finance.models import DailySalesSheet

        if sheet.status != DailySalesSheet.Status.OPEN:
            raise ValueError(
                f"Sheet {sheet.pk} is already {sheet.status} — cannot close again."
            )

        # Manual close — enforce closing time
        if not auto:
            schedule = self.get_close_schedule()
            now      = timezone.now()

            if now < schedule['attendant_lock_at']:
                # Calculate how long until closing time
                mins_remaining = int(
                    (schedule['attendant_lock_at'] - now).total_seconds() / 60
                )
                raise ValueError(
                    f"Sheet cannot be closed until {self.branch.closing_time.strftime('%H:%M')}. "
                    f"{mins_remaining} minute(s) remaining."
                )

        # Block auto-close if non-carryover pending payments exist
        if auto and self.has_pending_payments(sheet):
            count = self.get_pending_payment_count(sheet)
            logger.warning(
                'SheetEngine: auto-close blocked for sheet %s — '
                '%d pending payment(s) unresolved. BM notified.',
                sheet.pk,
                count,
            )
            self._notify_bm_pending_payments(sheet, count)
            return sheet

        # Freeze totals
        self._snapshot_totals(sheet)

        sheet.status    = (
            DailySalesSheet.Status.AUTO_CLOSED
            if auto
            else DailySalesSheet.Status.CLOSED
        )
        sheet.closed_by = closed_by
        sheet.closed_at = timezone.now()
        sheet.save()

        logger.info(
            'SheetEngine: sheet %s closed — %s',
            sheet.pk,
            sheet.status,
        )

        return sheet

    # ── Totals snapshot ───────────────────────────────────────────

    def _snapshot_totals(self, sheet) -> None:
        """
        Compute and freeze all financial totals on the sheet.
        Called once at close — never called again.
        """
        from apps.jobs.models import Job
        from apps.finance.models import PettyCash, CreditPayment

        jobs = Job.objects.filter(
            daily_sheet=sheet,
            status=Job.COMPLETE,
        )

        total_jobs        = jobs.count()
        total_cash        = self._sum(jobs, 'CASH')
        total_momo        = self._sum(jobs, 'MOMO')
        total_pos         = self._sum(jobs, 'POS')
        total_credit      = self._sum(jobs, 'CREDIT')
        total_fresh       = self._sum_fresh(jobs)
        total_deposits    = self._sum_deposits(jobs)
        total_balances    = self._sum_balance_collections(sheet)
        total_refunds     = self._sum_refunds(sheet)
        total_damages     = self._sum_damages(sheet)
        total_petty       = self._sum_petty_cash(sheet)
        total_credit_sett = self._sum_credit_settlements(sheet)

        net_cash = total_cash - total_refunds - total_petty

        sheet.total_jobs_created   = total_jobs
        sheet.total_fresh_revenue  = total_fresh
        sheet.total_deposits       = total_deposits
        sheet.total_balances       = total_balances
        sheet.total_cash           = total_cash
        sheet.total_momo           = total_momo
        sheet.total_pos            = total_pos
        sheet.total_credit_issued  = total_credit
        sheet.total_refunds        = total_refunds
        sheet.total_damages        = total_damages
        sheet.total_petty_cash_out = total_petty
        sheet.net_cash_in_till     = net_cash
        sheet.save(update_fields=[
            'total_jobs_created', 'total_fresh_revenue',
            'total_deposits', 'total_balances',
            'total_cash', 'total_momo', 'total_pos',
            'total_credit_issued', 'total_refunds',
            'total_damages', 'total_petty_cash_out',
            'net_cash_in_till',
        ])

    def _sum(self, jobs, method: str):
        from django.db.models import Sum
        result = jobs.filter(payment_method=method).aggregate(
            total=Sum('amount_paid')
        )['total']
        return result or 0

    def _sum_fresh(self, jobs):
        """Jobs that had no prior deposit — full payment in one go."""
        from django.db.models import Sum
        result = jobs.filter(deposit_percentage=100).aggregate(
            total=Sum('amount_paid')
        )['total']
        return result or 0

    def _sum_deposits(self, jobs):
        """Jobs where only a deposit was collected."""
        from django.db.models import Sum
        result = jobs.filter(deposit_percentage=70).aggregate(
            total=Sum('amount_paid')
        )['total']
        return result or 0

    def _sum_balance_collections(self, sheet):
        """
        Cash collected today as balance payments on prior-day jobs.
        These are jobs NOT on today's sheet but paid today.
        """
        from apps.jobs.models import Job
        from django.db.models import Sum
        result = Job.objects.filter(
            branch=sheet.branch,
            status=Job.COMPLETE,
            updated_at__date=sheet.date,
        ).exclude(
            daily_sheet=sheet,
        ).aggregate(
            total=Sum('amount_paid')
        )['total']
        return result or 0

    def _sum_refunds(self, sheet):
        from apps.jobs.models import Job
        from django.db.models import Sum
        result = Job.objects.filter(
            daily_sheet=sheet,
            status=Job.CANCELLED,
            amount_paid__isnull=False,
        ).aggregate(
            total=Sum('amount_paid')
        )['total']
        return result or 0

    def _sum_damages(self, sheet):
        from apps.jobs.models import Job
        from django.db.models import Sum
        result = Job.objects.filter(
            daily_sheet=sheet,
            status=Job.CANCELLED,
            cancellation_fee__isnull=False,
        ).aggregate(
            total=Sum('cancellation_fee')
        )['total']
        return result or 0

    def _sum_petty_cash(self, sheet):
        from apps.finance.models import PettyCash
        from django.db.models import Sum
        result = PettyCash.objects.filter(
            daily_sheet=sheet,
        ).aggregate(
            total=Sum('amount')
        )['total']
        return result or 0

    def _sum_credit_settlements(self, sheet):
        from apps.finance.models import CreditPayment
        from django.db.models import Sum
        result = CreditPayment.objects.filter(
            daily_sheet=sheet,
        ).aggregate(
            total=Sum('amount')
        )['total']
        return result or 0

    # ── Notifications ─────────────────────────────────────────────

    def _notify_bm_pending_payments(self, sheet, count: int) -> None:
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            bm = CustomUser.objects.filter(
                branch=self.branch,
                role__name='BRANCH_MANAGER',
                is_active=True,
            ).first()

            if bm:
                notify(
                    recipient=bm,
                    verb='SHEET_CLOSE_BLOCKED',
                    message=(
                        f"{count} job(s) still pending payment on today's sheet. "
                        f"Resolve before the sheet can close."
                    ),
                    link='/portal/jobs/?status=PENDING_PAYMENT',
                )
        except Exception:
            logger.exception(
                'SheetEngine: failed to notify BM for sheet %s', sheet.pk
            )
    @transaction.atomic
    def carry_forward_pending_jobs(self, sheet) -> int:
        """
        At hard lock (closing_time + CASHIER_LOCK_AFTER), mark all
        remaining PENDING_PAYMENT jobs as carried forward to next sheet.
        Returns count of jobs carried forward.
        """
        from apps.jobs.models import Job

        pending_jobs = Job.objects.filter(
            daily_sheet=sheet,
            status=Job.PENDING_PAYMENT,
        )

        count = pending_jobs.count()
        if count:
            pending_jobs.update(carried_forward=True)
            logger.info(
                'SheetEngine: %d job(s) carried forward from sheet %s',
                count,
                sheet.pk,
            )
            self._notify_bm_pending_payments(sheet, count)

        return count

    def get_branch_lock_status(self) -> dict:
        """
        Returns the current lock state for the branch.
        Used by the frontend to show/hide the New Job button.

        Returns dict with:
            can_create_jobs  : bool
            can_close_sheet  : bool
            lock_reason      : str or None
            schedule         : dict of close timestamps
            mins_to_close    : int (negative if past closing time)
        """
        now      = timezone.now()
        schedule = self.get_close_schedule()

        mins_to_close = int(
            (schedule['attendant_lock_at'] - now).total_seconds() / 60
        )

        can_create = now < schedule['attendant_lock_at']
        can_close  = now >= schedule['attendant_lock_at']

        lock_reason = None
        if not can_create:
            if mins_to_close > 0:
                lock_reason = f"Branch closes in {mins_to_close} minute(s)."
            else:
                lock_reason = (
                    f"Branch closed at {self.branch.closing_time.strftime('%H:%M')}. "
                    f"No new jobs can be recorded."
                )

        return {
            'can_create_jobs' : can_create,
            'can_close_sheet' : can_close,
            'lock_reason'     : lock_reason,
            'mins_to_close'   : mins_to_close,
            'schedule'        : {
                'warning_at'        : schedule['warning_at'].isoformat(),
                'attendant_lock_at' : schedule['attendant_lock_at'].isoformat(),
                'cashier_lock_at'   : schedule['cashier_lock_at'].isoformat(),
                'bm_autoclose_at'   : schedule['bm_autoclose_at'].isoformat(),
                'closing_time'      : self.branch.closing_time.strftime('%H:%M'),
            },
        }
    
    # ── Class-level convenience ───────────────────────────────────

    @classmethod
    def open_for_branch(cls, branch, **kwargs):
        """Shorthand: SheetEngine.open_for_branch(branch)"""
        return cls(branch).open_sheet(**kwargs)

    @classmethod
    def close_for_branch(cls, branch, sheet, **kwargs):
        """Shorthand: SheetEngine.close_for_branch(branch, sheet)"""
        return cls(branch).close_sheet(sheet, **kwargs)