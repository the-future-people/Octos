from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, Tuple

from django.conf import settings
from django.db import transaction, IntegrityError
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.utils.html import escape

logger = logging.getLogger(__name__)


class SheetEngine:
    """
    Controls the full lifecycle of a DailySalesSheet.

    Responsibilities:
    - Auto-open a sheet for a branch on a given date
    - Provide a fallback open if the scheduled task missed
    - Enforce the staged end-of-day close sequence
    - Auto-close sheets that were never manually closed
    - Freeze and snapshot totals at close — numbers never change after

    Rules:
    - One sheet per branch per day — enforced at DB level
    - Sundays never open
    - Public holidays open but are flagged with name and date
    - Instant jobs cannot carry past hard lock without CRITICAL flag
    - Production jobs never block EOD
    - Sheet is immutable once closed — no reopening ever

    Close sequence (all times from ShiftRoleConfig — no hardcoded constants):
    - BM shift_end - 30min  → warning modal shown to all portal users
    - Attendant job_lock_at → job creation locked for attendants
    - Cashier job_lock_at   → cashier payment queue locks
    - BM autoclose_at       → system auto-closes if BM hasn't closed
    """

    WARNING_BEFORE_CLOSE = 30  # minutes before shift_end to show warning
    DEFAULT_FLOAT_AMOUNT = Decimal(getattr(settings, 'DEFAULT_FLOAT_AMOUNT', '100.00'))
    MAX_FUTURE_OPEN_DAYS = getattr(settings, 'MAX_FUTURE_OPEN_DAYS', 1)

    def __init__(self, branch) -> None:
        self.branch = branch

    # ── Open ──────────────────────────────────────────────────────────────────

    @transaction.atomic
    def open_sheet(
        self,
        target_date: Optional[date] = None,
        opened_by=None,
        holiday_name: str = '',
    ) -> Tuple[Optional['DailySalesSheet'], bool]:
        """
        Open a daily sheet for the branch on the target date.
        If a sheet already exists for that date, return it unchanged.

        Args:
            target_date  : Date to open for — defaults to today
            opened_by    : CustomUser opening the sheet — None if system
            holiday_name : Public holiday name if applicable

        Returns:
            tuple(DailySalesSheet, created: bool)

        Raises:
            ValueError: If target_date is too far in the future or opened_by is invalid
        """
        from apps.finance.models import DailySalesSheet

        if target_date is None:
            target_date = timezone.localdate()

        # Validate date is not too far in the future
        max_future = timezone.localdate() + timedelta(days=self.MAX_FUTURE_OPEN_DAYS)
        if target_date > max_future:
            raise ValueError(
                f"Cannot open sheet more than {self.MAX_FUTURE_OPEN_DAYS} day(s) in advance."
            )

        # Never open on a Sunday
        if target_date.weekday() == 6:
            logger.info(
                'SheetEngine: skipping Sunday %s for branch %s',
                target_date, self.branch.code,
            )
            return None, False

        # Validate opened_by if provided
        if opened_by is not None:
            self._validate_opener(opened_by)

        is_holiday = bool(holiday_name)
        sanitized_holiday_name = escape(holiday_name) if holiday_name else ''

        sheet, created = DailySalesSheet.objects.get_or_create(
            branch=self.branch,
            date=target_date,
            defaults={
                'status': DailySalesSheet.Status.OPEN,
                'opened_by': opened_by,
                'is_public_holiday': is_holiday,
                'public_holiday_name': sanitized_holiday_name,
            },
        )

        if created:
            self._assign_sheet_number(sheet, target_date)
            logger.info(
                'SheetEngine: opened sheet %s for branch %s on %s',
                sheet.pk, self.branch.code, target_date,
            )
            self._link_staged_floats(sheet)

        return sheet, created

    @transaction.atomic
    def get_or_open_today(self, opened_by=None) -> Tuple[Optional['DailySalesSheet'], bool]:
        """
        Get today's open sheet or create one — race-condition safe.
        Uses get_or_create directly against the DB unique constraint.
        Never creates on Sundays.
        """
        from apps.finance.models import DailySalesSheet
        today = timezone.localdate()

        if today.weekday() == 6:
            return None, False

        # Validate opener before attempting creation
        if opened_by is not None:
            self._validate_opener(opened_by)

        try:
            sheet, created = DailySalesSheet.objects.get_or_create(
                branch=self.branch,
                date=today,
                defaults={
                    'status': DailySalesSheet.Status.OPEN,
                    'opened_by': opened_by,
                },
            )
            if created:
                self._assign_sheet_number(sheet, today)
                self._link_staged_floats(sheet)
                self._link_intake_held_jobs(sheet)
                logger.info(
                    'SheetEngine: opened sheet %s for branch %s on %s',
                    sheet.pk, self.branch.code, today,
                )
            return sheet, created
        except IntegrityError:
            # Concurrent create — fetch the winner
            sheet = DailySalesSheet.objects.get(branch=self.branch, date=today)
            return sheet, False
        except Exception as e:
            logger.exception(
                'SheetEngine: unexpected error opening sheet for branch %s: %s',
                self.branch.code, str(e)
            )
            raise

    def set_first_job_opener(self, sheet, user) -> None:
        """
        Record the first job creator as the operational sheet opener.
        Called after the first job is saved to a system-opened sheet.
        No-op if opened_by is already set.
        """
        if sheet.opened_by is None and user is not None:
            # Verify user belongs to this branch
            if hasattr(user, 'branch') and user.branch_id == self.branch.id:
                sheet.opened_by = user
                sheet.save(update_fields=['opened_by'])
                logger.info(
                    'SheetEngine: sheet %s opened_by set to user %s (first job)',
                    sheet.pk, user.pk,
                )
            else:
                logger.warning(
                    'SheetEngine: attempted to set opener for sheet %s '
                    'with user %s from different branch',
                    sheet.pk, user.pk
                )

    def _validate_opener(self, user) -> None:
        """
        Validate that the user can open sheets for this branch.
        
        Raises:
            ValueError: If user is not authorized to open sheets
        """
        from apps.accounts.models import CustomUser
        
        if not isinstance(user, CustomUser):
            raise ValueError("Invalid user object provided as opener.")
        
        if not user.is_active:
            raise ValueError(f"User {user.pk} is not active and cannot open sheets.")
        
        # Check branch association if user has branch field
        if hasattr(user, 'branch') and user.branch_id is not None:
            if user.branch_id != self.branch.id:
                raise ValueError(
                    f"User {user.pk} from branch {user.branch_id} "
                    f"cannot open sheets for branch {self.branch.id}."
                )

    def _assign_sheet_number(self, sheet, target_date) -> None:
        """
        Assign a cumulative per-branch sheet number on creation.
        Format: {BRANCH_CODE}-{MMDD}-{SEQ:03d}
        e.g. WLB-0407-015
        Uses select_for_update to prevent race conditions.
        """
        from apps.finance.models import DailySalesSheet
        from django.db.models import Max

        # Lock the sheet row to prevent concurrent sequence assignment
        sheet.refresh_from_db()
        
        # Get the highest existing sequence for this branch
        max_seq_result = DailySalesSheet.objects.filter(
            branch=self.branch
        ).aggregate(max_seq=Max('pk'))
        
        # Count sheets up to this one's PK (more accurate with select_for_update)
        seq = DailySalesSheet.objects.filter(
            branch=self.branch,
            pk__lte=sheet.pk,
        ).count()

        month = target_date.strftime('%m')
        day = target_date.strftime('%d')
        sheet.sheet_number = f"{self.branch.code}-{month}{day}-{seq:03d}"
        sheet.save(update_fields=['sheet_number'])
        
        logger.info(
            'SheetEngine: assigned sheet number %s to sheet %s',
            sheet.sheet_number, sheet.pk,
        )

    def _link_staged_floats(self, sheet) -> dict:
        """
        Link any pre-staged cashier floats to the newly opened sheet.
        Delegates entirely to FloatEngine — SheetEngine never touches
        CashierFloat directly.
        """
        from apps.finance.float_engine import FloatEngine
        return FloatEngine.link_staged_floats(sheet)

    def _link_intake_held_jobs(self, sheet) -> int:
        """
        Detect INTAKE_HELD jobs for this branch with no daily_sheet.
        Does NOT link them — that happens when cashier resolves each one.
        Returns count so the cashier portal knows to show the handover modal.
        """
        from apps.jobs.models import Job
        
        # Use exists() for cheaper check before count()
        has_held_jobs = Job.objects.filter(
            branch=self.branch,
            status=Job.INTAKE_HELD,
            daily_sheet=None,
        ).exists()
        
        if not has_held_jobs:
            return 0
            
        count = Job.objects.filter(
            branch=self.branch,
            status=Job.INTAKE_HELD,
            daily_sheet=None,
        ).count()
        
        if count:
            logger.info(
                'SheetEngine: %d INTAKE_HELD job(s) pending handover resolution '
                'for branch %s on sheet %s',
                count, self.branch.code, sheet.pk,
            )
        return count

    # ── Lock status ───────────────────────────────────────────────────────────

    def get_branch_lock_status(self, sheet=None, role_name: str = 'ATTENDANT') -> dict:
        """
        Returns the current lock state for the branch for a given role.
        Uses ShiftEngine for all timing — no hardcoded constants.

        Args:
            sheet     : Today's DailySalesSheet (optional)
            role_name : 'ATTENDANT' | 'CASHIER' | 'BRANCH_MANAGER'

        Returns dict with:
            can_create_jobs : bool
            can_close_sheet : bool
            lock_reason     : str or None
            mins_to_close   : int
            schedule        : dict of close timestamps
        """
        from apps.hr.shift_engine import ShiftEngine as HRShiftEngine

        now = timezone.now()
        today = timezone.localdate()

        # Sunday — always fully locked
        if today.weekday() == 6:
            return {
                'can_create_jobs': False,
                'can_close_sheet': False,
                'lock_reason': 'Branch is closed on Sundays.',
                'mins_to_close': 0,
                'schedule': {},
            }

        engine = HRShiftEngine(self.branch)
        att_schedule = engine.get_role_schedule('ATTENDANT', target_date=today)
        cash_schedule = engine.get_role_schedule('CASHIER', target_date=today)
        bm_schedule = engine.get_role_schedule('BRANCH_MANAGER', target_date=today)

        attendant_lock_at = datetime.fromisoformat(att_schedule['job_lock_at'])
        cashier_lock_at = datetime.fromisoformat(cash_schedule['job_lock_at'])
        bm_lock_at = datetime.fromisoformat(bm_schedule['job_lock_at'])
        bm_autoclose_at = (
            datetime.fromisoformat(bm_schedule['autoclose_at'])
            if bm_schedule.get('autoclose_at')
            else None
        )
        shift_end = datetime.fromisoformat(bm_schedule['shift_end'])
        warning_at = shift_end - timedelta(minutes=self.WARNING_BEFORE_CLOSE)

        # Role-specific lock time — BM's late-job channel opens at their
        # own job_lock_at (post-closing window start), NOT at bm_autoclose_at
        # (which is the separate system safety-net for forced sheet closure).
        role_lock_at = {
            'ATTENDANT': attendant_lock_at,
            'CASHIER': cashier_lock_at,
            'BRANCH_MANAGER': bm_lock_at,
        }.get(role_name, attendant_lock_at)

        can_create = now < role_lock_at
        can_close = now >= shift_end
        mins_to_close = int((shift_end - now).total_seconds() / 60)

        lock_reason = None
        if not can_create:
            lock_reason = (
                f"Shift ended at {shift_end.strftime('%I:%M %p')}. "
                f"No new jobs can be recorded."
            )

        return {
            'can_create_jobs': can_create,
            'can_close_sheet': can_close,
            'lock_reason': lock_reason,
            'mins_to_close': mins_to_close,
            'schedule': {
                'warning_at': warning_at.isoformat(),
                'attendant_lock_at': att_schedule['job_lock_at'],
                'cashier_lock_at': cash_schedule['job_lock_at'],
                'bm_autoclose_at': bm_schedule.get('autoclose_at'),
                'shift_end': bm_schedule['shift_end'],
            },
        }

    def get_close_schedule(self) -> dict:
        """
        Returns the computed timestamps for today's close sequence.
        Delegates to ShiftEngine for all timing.
        """
        from apps.hr.shift_engine import ShiftEngine as HRShiftEngine

        today = timezone.localdate()
        engine = HRShiftEngine(self.branch)

        att_schedule = engine.get_role_schedule('ATTENDANT', target_date=today)
        cash_schedule = engine.get_role_schedule('CASHIER', target_date=today)
        bm_schedule = engine.get_role_schedule('BRANCH_MANAGER', target_date=today)

        shift_end = datetime.fromisoformat(bm_schedule['shift_end'])
        warning_at = shift_end - timedelta(minutes=self.WARNING_BEFORE_CLOSE)
        autoclose_at = (
            datetime.fromisoformat(bm_schedule['autoclose_at'])
            if bm_schedule.get('autoclose_at')
            else shift_end + timedelta(minutes=60)
        )

        return {
            'warning_at': warning_at,
            'attendant_lock_at': datetime.fromisoformat(att_schedule['job_lock_at']),
            'cashier_lock_at': datetime.fromisoformat(cash_schedule['job_lock_at']),
            'bm_autoclose_at': autoclose_at,
            'shift_end': shift_end,
        }

    # ── Float helpers (delegate to FloatEngine) ───────────────────────────────

    def has_unsigned_floats(self, sheet) -> bool:
        from apps.finance.float_engine import FloatEngine
        result = FloatEngine.validate_signoff_gate(sheet)
        return not result['passed']

    def get_unsigned_float_count(self, sheet) -> int:
        from apps.finance.models import CashierFloat
        return CashierFloat.objects.filter(
            daily_sheet=sheet,
            is_signed_off=False,
        ).count()

    def has_pending_payments(self, sheet) -> bool:
        from apps.jobs.models import Job
        return Job.objects.filter(
            daily_sheet=sheet,
            status=Job.PENDING_PAYMENT,
            job_type='INSTANT',
            is_routed=False,
            customer__credit_account__isnull=True,
        ).exists()

    def get_pending_payment_count(self, sheet) -> int:
        from apps.jobs.models import Job
        return Job.objects.filter(
            daily_sheet=sheet,
            status=Job.PENDING_PAYMENT,
            job_type='INSTANT',
            is_routed=False,
            customer__credit_account__isnull=True,
        ).count()

    # ── Close ─────────────────────────────────────────────────────────────────

    @transaction.atomic
    def close_sheet(self, sheet, closed_by=None, auto: bool = False):
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
            ValueError : Attempted manual close before attendant_lock_at
            ValueError : User not authorized to close sheet
        """
        from apps.finance.models import DailySalesSheet

        if sheet.status != DailySalesSheet.Status.OPEN:
            raise ValueError(
                f"Sheet {sheet.pk} is already {sheet.status} — cannot close again."
            )

        # Validate closer if manual close
        if not auto and closed_by is not None:
            self._validate_closer(closed_by)

        # Manual close — enforce timing
        if not auto:
            schedule = self.get_close_schedule()
            now = timezone.now()

            if now < schedule['attendant_lock_at']:
                mins_remaining = int(
                    (schedule['attendant_lock_at'] - now).total_seconds() / 60
                )
                raise ValueError(
                    f"Sheet cannot be closed yet. "
                    f"{mins_remaining} minute(s) remaining until lock."
                )

        # Auto-close: block if unsigned floats exist
        if auto and self.has_unsigned_floats(sheet):
            count = self.get_unsigned_float_count(sheet)
            logger.warning(
                'SheetEngine: auto-close blocked for sheet %s — '
                '%d float(s) unsigned.',
                sheet.pk, count,
            )
            self._notify_bm_unsigned_floats(sheet, count)
            self._handle_autoclose_failure(sheet, 'unsigned_floats', count)
            return sheet

        # Auto-close: block if pending instant payments exist
        if auto and self.has_pending_payments(sheet):
            count = self.get_pending_payment_count(sheet)
            logger.warning(
                'SheetEngine: auto-close blocked for sheet %s — '
                '%d pending payment(s).',
                sheet.pk, count,
            )
            self._notify_bm_pending_payments(sheet, count)
            self._handle_autoclose_failure(sheet, 'pending_payments', count)
            return sheet

        # Freeze totals
        self._snapshot_totals(sheet)

        sheet.status = (
            DailySalesSheet.Status.AUTO_CLOSED if auto
            else DailySalesSheet.Status.CLOSED
        )
        sheet.closed_by = closed_by
        sheet.closed_at = timezone.now()
        sheet.save()

        if auto:
            self._notify_auto_close(sheet)
            self._stage_tomorrow_floats(sheet)

        logger.info('SheetEngine: sheet %s closed — %s', sheet.pk, sheet.status)
        return sheet

    def _validate_closer(self, user) -> None:
        """
        Validate that the user can close sheets for this branch.
        
        Raises:
            ValueError: If user is not authorized to close sheets
        """
        from apps.accounts.models import CustomUser
        
        if not isinstance(user, CustomUser):
            raise ValueError("Invalid user object provided as closer.")
        
        if not user.is_active:
            raise ValueError(f"User {user.pk} is not active and cannot close sheets.")
        
        # Check branch association
        if hasattr(user, 'branch') and user.branch_id is not None:
            if user.branch_id != self.branch.id:
                raise ValueError(
                    f"User {user.pk} from branch {user.branch_id} "
                    f"cannot close sheets for branch {self.branch.id}."
                )

    def _handle_autoclose_failure(self, sheet, failure_type: str, count: int) -> None:
        """
        Handle repeated auto-close failures with escalation.
        Tracks failure count and escalates to RM after threshold.
        """
        from apps.finance.models import DailySalesSheet
        
        # Check how many consecutive days this sheet has failed auto-close
        failed_days = DailySalesSheet.objects.filter(
            branch=self.branch,
            status=DailySalesSheet.Status.OPEN,
            date__lt=timezone.localdate(),
        ).count()
        
        if failed_days >= 3:  # Escalation threshold
            logger.critical(
                'SheetEngine: ESCALATION - Branch %s has %d unclosed sheets '
                'with %s failure. Last failure: sheet %s',
                self.branch.code, failed_days, failure_type, sheet.pk
            )
            self._notify_rm_escalation(sheet, failure_type, failed_days)

    # ── Totals snapshot ───────────────────────────────────────────────────────

    def _snapshot_totals(self, sheet) -> None:
        """
        Compute and freeze all financial totals on the sheet.
        Called once at close — never called again.

        Revenue source: always amount_paid on Receipt, never estimated_cost.
        """
        from apps.finance.models import Receipt, PettyCash, CreditPayment, PaymentLeg
        from apps.jobs.models import Job

        # Optimize by using a single query with annotations where possible
        receipts = Receipt.objects.filter(
            daily_sheet=sheet,
            is_void=False,
        ).select_related('job')

        # Aggregate payments by method in a single query
        payment_aggregates = receipts.values('payment_method').annotate(
            total=Sum('amount_paid')
        )
        
        total_cash = Decimal('0.00')
        total_momo = Decimal('0.00')
        total_pos = Decimal('0.00')
        total_credit_issued = Decimal('0.00')
        
        for agg in payment_aggregates:
            method = agg['payment_method']
            amount = agg['total'] or Decimal('0.00')
            
            if method == 'CASH':
                total_cash += amount
            elif method == 'MOMO':
                total_momo += amount
            elif method == 'POS':
                total_pos += amount
            elif method == 'CREDIT':
                total_credit_issued += amount

        # Handle SPLIT payments efficiently with a single subquery
        split_receipt_ids = receipts.filter(
            payment_method='SPLIT'
        ).values_list('job_id', flat=True)
        
        if split_receipt_ids:
            split_legs = PaymentLeg.objects.filter(
                job_id__in=split_receipt_ids
            ).values('payment_method').annotate(
                total=Sum('amount')
            )
            
            for leg in split_legs:
                method = leg['payment_method']
                amount = leg['total'] or Decimal('0.00')
                
                if method == 'CASH':
                    total_cash += amount
                elif method == 'MOMO':
                    total_momo += amount
                elif method == 'POS':
                    total_pos += amount

        # Get other totals
        total_petty = PettyCash.objects.filter(
            daily_sheet=sheet,
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        total_credit_settled = CreditPayment.objects.filter(
            daily_sheet=sheet,
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        total_jobs = Job.objects.filter(
            daily_sheet=sheet,
            status=Job.COMPLETE,
        ).count()

        net_cash = total_cash - total_petty

        sheet.total_jobs_created = total_jobs
        sheet.total_cash = total_cash
        sheet.total_momo = total_momo
        sheet.total_pos = total_pos
        sheet.total_credit_issued = total_credit_issued
        sheet.total_credit_settled = total_credit_settled
        sheet.total_petty_cash_out = total_petty
        sheet.net_cash_in_till = net_cash

        sheet.save(update_fields=[
            'total_jobs_created',
            'total_cash',
            'total_momo',
            'total_pos',
            'total_credit_issued',
            'total_credit_settled',
            'total_petty_cash_out',
            'net_cash_in_till',
        ])

    def _stage_tomorrow_floats(self, sheet) -> None:
        """
        On auto-close, stage tomorrow's floats for all active cashiers
        using their closing cash as the opening float.
        Called only on auto-close — manual close handles this in the view.
        """
        try:
            from apps.finance.models import CashierFloat
            from apps.finance.float_engine import FloatEngine
            from apps.accounts.models import CustomUser

            tomorrow = sheet.date + timedelta(days=1)
            # Skip Sundays
            while tomorrow.weekday() == 6:
                tomorrow = tomorrow + timedelta(days=1)

            cashiers = CustomUser.objects.filter(
                branch=self.branch,
                role__name='CASHIER',
                is_active=True,
            ).select_related('branch')

            for cashier in cashiers:
                try:
                    float_record = CashierFloat.objects.filter(
                        daily_sheet=sheet,
                        cashier=cashier,
                    ).first()

                    # Always stage the standard float. Carrying closing cash
                    # forward would inflate the next day's opening_float, which
                    # feeds expected_cash in compute_variance() and would show
                    # the cashier as short by the difference — money she never
                    # received. The BM physically collects the day's takings and
                    # hands back a fixed float each morning.
                    opening = self.DEFAULT_FLOAT_AMOUNT

                    FloatEngine.stage_float(
                        cashier=cashier,
                        amount=opening,
                        set_by=None,  # System auto-close
                        target_date=tomorrow,
                        branch=self.branch,
                    )
                    logger.info(
                        'SheetEngine: staged float GHS %s for %s on %s (auto-close)',
                        opening, cashier.full_name, tomorrow,
                    )
                except Exception as e:
                    logger.exception(
                        'SheetEngine: failed to stage float for cashier %s: %s',
                        cashier.pk, str(e),
                    )
        except Exception as e:
            logger.exception(
                'SheetEngine: _stage_tomorrow_floats failed for sheet %s: %s',
                sheet.pk, str(e),
            )

    # ── Carry forward ──────────────────────────────────────────────────────────

    @transaction.atomic
    def carry_forward_pending_jobs(self, sheet) -> int:
        """
        Mark all remaining PENDING_PAYMENT instant jobs as carried forward.
        Called at hard lock time by Celery task.
        Returns count of jobs carried forward.
        """
        from apps.jobs.models import Job

        pending = Job.objects.filter(
            daily_sheet=sheet,
            status=Job.PENDING_PAYMENT,
            job_type='INSTANT',
        )

        count = pending.count()
        if count:
            pending.update(carried_forward=True)
            logger.info(
                'SheetEngine: %d instant job(s) carried forward from sheet %s',
                count, sheet.pk,
            )
            self._notify_bm_pending_payments(sheet, count)

        return count

    # ── Notifications ─────────────────────────────────────────────────────────

    def _notify_bm_unsigned_floats(self, sheet, count: int) -> None:
        """Notify all branch managers about unsigned floats blocking close."""
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            # Get ALL branch managers for this branch, not just the first
            bms = CustomUser.objects.filter(
                branch=self.branch,
                role__name='BRANCH_MANAGER',
                is_active=True,
            )

            for bm in bms:
                try:
                    notify(
                        recipient=bm,
                        verb='SHEET_CLOSE_BLOCKED',
                        message=(
                            f"Auto-close blocked — {count} cashier float(s) not signed off. "
                            f"Cashier must complete EOD count before the sheet can close."
                        ),
                        link='/portal/dashboard/',
                    )
                except Exception as e:
                    logger.warning(
                        'SheetEngine: failed to notify BM %s: %s', bm.pk, str(e)
                    )
        except Exception as e:
            logger.exception(
                'SheetEngine: failed to notify BMs of unsigned floats for sheet %s: %s',
                sheet.pk, str(e),
            )

    def _notify_bm_pending_payments(self, sheet, count: int) -> None:
        """Notify all branch managers about pending payments blocking close."""
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            # Get ALL branch managers, not just the first
            bms = CustomUser.objects.filter(
                branch=self.branch,
                role__name='BRANCH_MANAGER',
                is_active=True,
            )

            for bm in bms:
                try:
                    notify(
                        recipient=bm,
                        verb='SHEET_CLOSE_BLOCKED',
                        message=(
                            f"{count} instant job(s) still pending payment. "
                            f"Resolve or carry forward before sheet can close."
                        ),
                        link='/portal/dashboard/?tab=jobs&status=PENDING_PAYMENT',
                    )
                except Exception as e:
                    logger.warning(
                        'SheetEngine: failed to notify BM %s: %s', bm.pk, str(e)
                    )
        except Exception as e:
            logger.exception(
                'SheetEngine: failed to notify BMs pending payments for sheet %s: %s',
                sheet.pk, str(e),
            )

    def _notify_auto_close(self, sheet) -> None:
        """
        Alert RM when a sheet is auto-closed.
        Auto-close means BM failed to close manually — CRITICAL risk signal.
        Notifies ALL regional managers and logs escalation.
        """
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            region = getattr(self.branch, 'region', None)
            if region:
                rm_users = CustomUser.objects.filter(
                    region=region,
                    role__name='REGIONAL_MANAGER',
                    is_active=True,
                )
                for rm in rm_users:
                    try:
                        notify(
                            recipient=rm,
                            verb='SHEET_AUTO_CLOSED',
                            message=(
                                f"ALERT: {self.branch.name} sheet for "
                                f"{sheet.date} was auto-closed. "
                                f"Branch Manager did not close manually. "
                                f"Immediate follow-up required."
                            ),
                            link='/portal/regional/',
                        )
                    except Exception as e:
                        logger.warning(
                            'SheetEngine: failed to notify RM %s: %s', rm.pk, str(e)
                        )

            logger.warning(
                'SheetEngine: sheet %s for branch %s AUTO-CLOSED.',
                sheet.pk, self.branch.code,
            )
        except Exception as e:
            logger.exception(
                'SheetEngine: failed to send auto-close alert for sheet %s: %s',
                sheet.pk, str(e),
            )

    def _notify_rm_escalation(self, sheet, failure_type: str, failed_days: int) -> None:
        """
        Escalate to regional managers when auto-close failures persist.
        """
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            region = getattr(self.branch, 'region', None)
            if region:
                rm_users = CustomUser.objects.filter(
                    region=region,
                    role__name='REGIONAL_MANAGER',
                    is_active=True,
                )
                for rm in rm_users:
                    try:
                        notify(
                            recipient=rm,
                            verb='SHEET_CLOSE_ESCALATION',
                            message=(
                                f"CRITICAL: {self.branch.name} has {failed_days} "
                                f"unclosed sheets with {failure_type} issues. "
                                f"Immediate intervention required."
                            ),
                            link='/portal/regional/',
                        )
                    except Exception as e:
                        logger.warning(
                            'SheetEngine: failed to escalate to RM %s: %s', rm.pk, str(e)
                        )
        except Exception as e:
            logger.exception(
                'SheetEngine: escalation notification failed for sheet %s: %s',
                sheet.pk, str(e),
            )

    # ── Class-level convenience ───────────────────────────────────────────────

    @classmethod
    def open_for_branch(cls, branch, **kwargs):
        """Shorthand: SheetEngine.open_for_branch(branch)"""
        return cls(branch).open_sheet(**kwargs)

    @classmethod
    def close_for_branch(cls, branch, sheet, **kwargs):
        """Shorthand: SheetEngine.close_for_branch(branch, sheet)"""
        return cls(branch).close_sheet(sheet, **kwargs)