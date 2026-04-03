"""
FloatEngine
===========
Single owner of all cashier float business logic.

Responsibilities:
  - Stage float (BM sets for tomorrow during EOD)
  - Link staged floats when sheet opens
  - Acknowledge float (cashier confirms denomination count)
  - Mid-day handover (cashier A → BM → cashier B)
  - EOD sign-off (last cashier of the day)
  - Float status resolution
  - EOD gate validation (for SheetEngine)
  - Tomorrow's float gate validation (for SheetEngine)

Design rules:
  - FloatEngine never touches DailySalesSheet directly
  - SheetEngine calls FloatEngine — never the reverse
  - All state changes fire Django signals for analytics
  - Every method returns a result dict — never raises for business logic errors
  - Only raises for programmer errors (wrong types, missing required fields)
"""

import logging
from decimal import Decimal
from django.utils import timezone
from django.db import transaction

logger = logging.getLogger(__name__)


class FloatEngine:

    # ── Stage float ───────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def stage_float(
        cls,
        cashier,
        amount: Decimal,
        set_by,
        target_date,
        branch,
    ) -> dict:
        """
        BM stages a float for a cashier for a future date.
        Called during EOD close — hard gate enforced by SheetEngine.

        Args:
            cashier     : CustomUser — the cashier receiving the float
            amount      : Decimal — GHS amount
            set_by      : CustomUser — the BM staging it
            target_date : date — the date this float is for (tomorrow)
            branch      : Branch — for validation

        Returns:
            {'ok': True, 'float': CashierFloat}
            {'ok': False, 'error': str}
        """
        from apps.finance.models import CashierFloat

        # Validate amount
        amount = Decimal(str(amount))
        if amount <= 0:
            return {'ok': False, 'error': 'Float amount must be greater than zero.'}

        # Validate cashier belongs to branch
        if getattr(cashier, 'branch_id', None) != branch.pk:
            return {
                'ok'   : False,
                'error': f"{cashier.full_name} does not belong to {branch.name}.",
            }

        # Validate target date is not Sunday
        if target_date.weekday() == 6:
            return {'ok': False, 'error': 'Cannot stage a float for Sunday.'}

        # Remove any existing staged float for this cashier/date
        existing = CashierFloat.objects.filter(
            cashier        = cashier,
            daily_sheet    = None,
            scheduled_date = target_date,
        )
        if existing.exists():
            existing.delete()
            logger.info(
                'FloatEngine: replaced existing staged float for %s on %s',
                cashier.full_name, target_date,
            )

        # Determine shift_sequence — default 1 for staged floats
        # Will be updated if this is a handover-generated float
        float_record = CashierFloat.objects.create(
            cashier        = cashier,
            daily_sheet    = None,
            scheduled_date = target_date,
            shift_sequence = 1,
            opening_float  = amount,
            float_set_by   = set_by,
            float_set_at   = timezone.now(),
        )

        logger.info(
            'FloatEngine: staged GHS %s float for %s on %s (set by %s)',
            amount, cashier.full_name, target_date, set_by.full_name,
        )

        return {'ok': True, 'float': float_record}

    # ── Link staged floats ────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def link_staged_floats(cls, sheet) -> dict:
        """
        Link any pre-staged floats to a newly opened sheet.
        Called by SheetEngine when sheet is created.

        Returns:
            {'linked': int, 'missing_cashiers': list}
        """
        from apps.finance.models import CashierFloat
        from apps.accounts.models import CustomUser

        staged = CashierFloat.objects.filter(
            daily_sheet     = None,
            scheduled_date  = sheet.date,
            cashier__branch = sheet.branch,
        )

        linked_count = staged.count()
        if linked_count:
            staged.update(
                daily_sheet    = sheet,
                scheduled_date = None,
            )
            logger.info(
                'FloatEngine: linked %d staged float(s) to sheet %s for %s',
                linked_count, sheet.pk, sheet.branch.code,
            )

        # Check which cashiers have no float for today
        cashiers_with_floats = CashierFloat.objects.filter(
            daily_sheet = sheet,
        ).values_list('cashier_id', flat=True)

        branch_cashiers = CustomUser.objects.filter(
            branch     = sheet.branch,
            role__name = 'CASHIER',
            is_active  = True,
        ).exclude(pk__in=cashiers_with_floats)

        missing = [c.full_name for c in branch_cashiers]

        if missing:
            logger.warning(
                'FloatEngine: no float staged for %s on sheet %s — BM must set manually.',
                ', '.join(missing), sheet.pk,
            )

        return {
            'linked'           : linked_count,
            'missing_cashiers' : missing,
        }

    # ── Acknowledge float ─────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def acknowledge(
        cls,
        float_record,
        breakdown: dict,
        cashier,
    ) -> dict:
        """
        Cashier acknowledges receipt of float with denomination count.
        Total must match opening_float exactly.

        Returns:
            {'ok': True, 'float': CashierFloat}
            {'ok': False, 'error': str, 'counted': float, 'expected': float}
        """
        from apps.finance.models import CashierFloat

        if float_record.morning_acknowledged:
            return {'ok': False, 'error': 'Float already acknowledged.'}

        if float_record.cashier_id != cashier.pk:
            return {'ok': False, 'error': 'This float does not belong to you.'}

        # Validate breakdown
        valid_denoms = {'1', '2', '5', '10', '20', '50', '100', '200'}
        for denom in breakdown:
            if str(denom) not in valid_denoms:
                return {
                    'ok'   : False,
                    'error': f"Invalid denomination: GHS {denom}.",
                }
            try:
                if int(breakdown[denom]) < 0:
                    raise ValueError
            except (ValueError, TypeError):
                return {
                    'ok'   : False,
                    'error': f"Invalid count for GHS {denom}.",
                }

        # Validate total matches
        counted   = CashierFloat.denomination_total(breakdown)
        expected  = float(float_record.opening_float)

        if abs(counted - expected) > 0.01:
            return {
                'ok'      : False,
                'error'   : (
                    f"Denomination total GHS {counted:.2f} does not match "
                    f"float amount GHS {expected:.2f}. Please recount."
                ),
                'counted' : counted,
                'expected': expected,
            }

        float_record.morning_acknowledged           = True
        float_record.morning_acknowledged_at        = timezone.now()
        float_record.opening_denomination_breakdown = {
            str(k): int(v) for k, v in breakdown.items()
        }
        float_record.save(update_fields=[
            'morning_acknowledged',
            'morning_acknowledged_at',
            'opening_denomination_breakdown',
            'updated_at',
        ])

        logger.info(
            'FloatEngine: float acknowledged by %s — GHS %s',
            cashier.full_name, float_record.opening_float,
        )

        return {'ok': True, 'float': float_record}

    # ── Mid-day handover ──────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def mid_day_handover(
        cls,
        float_record,
        handover_amount: Decimal,
        breakdown: dict,
        signed_off_by,
        shift_notes: str = '',
    ) -> dict:
        """
        Cashier A ends their shift mid-day and hands float to BM.
        System automatically stages same amount for next cashier.

        The next cashier's float is staged with shift_sequence = current + 1.
        BM must assign the next cashier before they can acknowledge.

        Returns:
            {'ok': True, 'float': CashierFloat, 'next_staged': CashierFloat}
            {'ok': False, 'error': str}
        """
        from apps.finance.models import CashierFloat

        if not float_record.morning_acknowledged:
            return {
                'ok'   : False,
                'error': 'Float has not been acknowledged — cannot sign off.',
            }

        if float_record.is_signed_off:
            return {'ok': False, 'error': 'Float already signed off.'}

        handover_amount = Decimal(str(handover_amount))
        if handover_amount < 0:
            return {'ok': False, 'error': 'Handover amount cannot be negative.'}

        # Record handover on current float
        float_record.is_handover                    = True
        float_record.handover_float                 = handover_amount
        float_record.handover_denomination_breakdown = {
            str(k): int(v) for k, v in breakdown.items()
        }
        float_record.handover_at    = timezone.now()
        float_record.is_signed_off  = True
        float_record.signed_off_by  = signed_off_by
        float_record.signed_off_at  = timezone.now()
        float_record.shift_notes    = shift_notes
        float_record.save(update_fields=[
            'is_handover',
            'handover_float',
            'handover_denomination_breakdown',
            'handover_at',
            'is_signed_off',
            'signed_off_by',
            'signed_off_at',
            'shift_notes',
            'updated_at',
        ])

        # Auto-stage next float with same amount
        # cashier is None — BM will assign when next cashier reports
        next_sequence = float_record.shift_sequence + 1
        next_float = CashierFloat.objects.create(
            daily_sheet    = float_record.daily_sheet,
            scheduled_date = None,
            cashier        = float_record.cashier,
            # Temporary — BM reassigns when next cashier reports
            # In future: rota system determines next cashier
            shift_sequence = next_sequence,
            opening_float  = handover_amount,
            float_set_by   = signed_off_by,
            float_set_at   = timezone.now(),
        )

        # Link current to next
        float_record.next_float = next_float
        float_record.save(update_fields=['next_float', 'updated_at'])

        logger.info(
            'FloatEngine: mid-day handover by %s — GHS %s handed over. '
            'Next float staged (sequence %d).',
            signed_off_by.full_name, handover_amount, next_sequence,
        )

        return {
            'ok'         : True,
            'float'      : float_record,
            'next_staged': next_float,
        }

    # ── EOD sign-off ──────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def sign_off(
        cls,
        float_record,
        closing_cash: Decimal,
        breakdown: dict,
        variance_notes: str,
        shift_notes: str,
        signed_off_by,
        is_overtime: bool = False,
        overtime_reason: str = '',
        overtime_until=None,
    ) -> dict:
        """
        EOD sign-off for the last cashier of the day.
        Computes variance automatically.

        Returns:
            {'ok': True, 'float': CashierFloat, 'variance': Decimal}
            {'ok': False, 'error': str}
        """
        if not float_record.morning_acknowledged:
            return {
                'ok'   : False,
                'error': 'Float has not been acknowledged — cannot sign off.',
            }

        if float_record.is_signed_off:
            return {'ok': False, 'error': 'Float already signed off.'}

        closing_cash = Decimal(str(closing_cash))
        if closing_cash < 0:
            return {'ok': False, 'error': 'Closing cash cannot be negative.'}

        # Variance notes mandatory if variance exists
        float_record.closing_cash                  = closing_cash
        float_record.closing_denomination_breakdown = {
            str(k): int(v) for k, v in (breakdown or {}).items()
        }

        # Compute variance
        float_record.compute_variance()

        if float_record.has_variance and not variance_notes.strip():
            return {
                'ok'   : False,
                'error': (
                    f"Variance of GHS {abs(float(float_record.variance)):.2f} detected. "
                    f"Please explain the discrepancy."
                ),
            }

        float_record.variance_notes = variance_notes
        float_record.shift_notes    = shift_notes
        float_record.signed_off_by  = signed_off_by
        float_record.signed_off_at  = timezone.now()
        float_record.is_signed_off  = True

        # Overtime
        if is_overtime:
            float_record.is_overtime     = True
            float_record.overtime_reason = overtime_reason
            float_record.overtime_until  = overtime_until

        float_record.save(update_fields=[
            'closing_cash',
            'closing_denomination_breakdown',
            'expected_cash',
            'variance',
            'variance_notes',
            'shift_notes',
            'signed_off_by',
            'signed_off_at',
            'is_signed_off',
            'is_overtime',
            'overtime_reason',
            'overtime_until',
            'updated_at',
        ])

        logger.info(
            'FloatEngine: EOD sign-off by %s — closing GHS %s, variance GHS %s',
            signed_off_by.full_name,
            closing_cash,
            float_record.variance,
        )

        return {
            'ok'      : True,
            'float'   : float_record,
            'variance': float_record.variance,
        }

    # ── Float status resolution ───────────────────────────────────────────────

    @classmethod
    def get_float_status(cls, cashier, branch, date=None) -> dict:
        """
        Returns current float state for a cashier on a given date.
        Single source of truth for CashierShiftStatusView.

        Returns:
            {
                'float_status'     : str (NO_FLOAT | PENDING_ACK | ACTIVE |
                                         PENDING_HANDOVER | SIGNED_OFF),
                'float_id'         : int | None,
                'sheet_id'         : int | None,
                'opening_float'    : str | None,
                'opening_breakdown': dict | None,
                'shift_sequence'   : int,
            }
        """
        from apps.finance.models import CashierFloat, DailySalesSheet

        if date is None:
            date = timezone.localdate()

        # Try to find float linked to today's sheet
        float_record = CashierFloat.objects.filter(
            cashier             = cashier,
            daily_sheet__date   = date,
            daily_sheet__branch = branch,
            is_signed_off       = False,
        ).order_by('-shift_sequence').first()

        # Try staged float
        if float_record is None:
            staged = CashierFloat.objects.filter(
                cashier        = cashier,
                daily_sheet    = None,
                scheduled_date = date,
            ).first()

            if staged:
                # Auto-link if sheet is open
                try:
                    open_sheet = DailySalesSheet.objects.get(
                        branch = branch,
                        date   = date,
                        status = DailySalesSheet.Status.OPEN,
                    )
                    already_linked = CashierFloat.objects.filter(
                        daily_sheet = open_sheet,
                        cashier     = cashier,
                    ).exists()

                    if not already_linked:
                        staged.daily_sheet    = open_sheet
                        staged.scheduled_date = None
                        staged.save(update_fields=[
                            'daily_sheet', 'scheduled_date', 'updated_at'
                        ])
                        logger.info(
                            'FloatEngine: auto-linked staged float %s to sheet %s',
                            staged.pk, open_sheet.pk,
                        )

                except DailySalesSheet.DoesNotExist:
                    pass

                float_record = staged

        if float_record is None:
            # Check if there's a signed-off float — shift complete
            signed_off = CashierFloat.objects.filter(
                cashier             = cashier,
                daily_sheet__date   = date,
                daily_sheet__branch = branch,
                is_signed_off       = True,
            ).order_by('-shift_sequence').first()

            if signed_off:
                return {
                    'float_status'     : 'SIGNED_OFF',
                    'float_id'         : signed_off.pk,
                    'sheet_id'         : signed_off.daily_sheet_id,
                    'opening_float'    : str(signed_off.opening_float),
                    'opening_breakdown': signed_off.opening_denomination_breakdown,
                    'shift_sequence'   : signed_off.shift_sequence,
                }

            return {
                'float_status'     : 'NO_FLOAT',
                'float_id'         : None,
                'sheet_id'         : None,
                'opening_float'    : None,
                'opening_breakdown': None,
                'shift_sequence'   : 0,
            }

        return {
            'float_status'     : float_record.float_status,
            'float_id'         : float_record.pk,
            'sheet_id'         : float_record.daily_sheet_id,
            'opening_float'    : str(float_record.opening_float),
            'opening_breakdown': float_record.opening_denomination_breakdown,
            'shift_sequence'   : float_record.shift_sequence,
        }

    # ── EOD gate: all cashiers signed off ─────────────────────────────────────

    @classmethod
    def validate_signoff_gate(cls, sheet) -> dict:
        """
        Called by SheetEngine before closing sheet.
        All cashier floats must be signed off.

        Returns:
            {'passed': True}
            {'passed': False, 'errors': list, 'unsigned': list}
        """
        from apps.finance.models import CashierFloat

        unsigned = CashierFloat.objects.filter(
            daily_sheet   = sheet,
            is_signed_off = False,
            morning_acknowledged = True,
        ).select_related('cashier')

        unacknowledged = CashierFloat.objects.filter(
            daily_sheet          = sheet,
            morning_acknowledged = False,
        ).select_related('cashier')

        errors  = []
        details = []

        for f in unsigned:
            errors.append(
                f"{f.cashier.full_name} has not completed EOD sign-off."
            )
            details.append(f.cashier.full_name)

        for f in unacknowledged:
            errors.append(
                f"{f.cashier.full_name} never acknowledged their float "
                f"of GHS {f.opening_float}."
            )
            details.append(f.cashier.full_name)

        if errors:
            return {
                'passed'  : False,
                'errors'  : errors,
                'unsigned': details,
            }

        return {'passed': True}

    # ── EOD gate: tomorrow's float set ────────────────────────────────────────

    @classmethod
    def validate_tomorrow_float_gate(cls, sheet) -> dict:
        """
        Called by SheetEngine before closing sheet.
        Checks if floats are staged for tomorrow for all active cashiers.

        Returns:
            {'passed': True}
            {'passed': False, 'errors': list, 'missing': list, 'warning': bool}
        """
        from apps.finance.models import CashierFloat
        from apps.accounts.models import CustomUser
        from datetime import timedelta

        tomorrow = sheet.date + timedelta(days=1)

        # Never require float for Sunday
        if tomorrow.weekday() == 6:
            return {'passed': True}

        # Find active cashiers for this branch
        branch_cashiers = CustomUser.objects.filter(
            branch     = sheet.branch,
            role__name = 'CASHIER',
            is_active  = True,
        )

        if not branch_cashiers.exists():
            return {'passed': True}

        # Check which cashiers have staged floats for tomorrow
        staged_cashier_ids = CashierFloat.objects.filter(
            daily_sheet    = None,
            scheduled_date = tomorrow,
            cashier__branch = sheet.branch,
        ).values_list('cashier_id', flat=True)

        missing = [
            c.full_name for c in branch_cashiers
            if c.pk not in staged_cashier_ids
        ]

        if missing:
            return {
                'passed' : False,
                'errors' : [
                    f"Float not set for tomorrow ({tomorrow}) for: "
                    f"{', '.join(missing)}. "
                    f"Set tomorrow's float before closing today's sheet."
                ],
                'missing': missing,
                'warning': False,
            }

        return {'passed': True}