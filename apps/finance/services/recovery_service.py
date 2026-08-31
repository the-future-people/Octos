"""
Stranded sheet recovery.

A daily sheet that could not be closed on its own day strands every day
after it: the next day's float is only staged during close, and there is
no other route in the system to set one. One missed close therefore
cascades until someone intervenes.

This service unwinds that, one day at a time, oldest first. Each recovery
stages a float if none exists, links it to the sheet, records a
retrospective sign-off against a physically counted figure, and closes the
sheet — which in turn stages the following day's float and unblocks it.

A branch manager may recover up to MAX_BM_RECOVERY_DAYS stranded days.
Beyond that the backlog is large enough to warrant a regional manager,
and the manager is blocked pending intervention.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


class RecoveryService:
    """Recovery of sheets that were never closed on their own day."""

    MAX_BM_RECOVERY_DAYS = 2

    # ── Read side ─────────────────────────────────────────────

    @classmethod
    def get_stranded_sheets(cls, branch):
        """
        OPEN sheets from before today, oldest first.

        Sundays are excluded — the branch does not trade, no sheet should
        exist, and one that somehow did would clog this list permanently.
        """
        from apps.finance.models import DailySalesSheet

        today = timezone.localdate()
        sheets = DailySalesSheet.objects.filter(
            branch = branch,
            status = DailySalesSheet.Status.OPEN,
            date__lt = today,
        ).order_by('date')

        return [s for s in sheets if s.date.weekday() != 6]

    # Roles the day-ceiling does not apply to. The ceiling exists to stop a
    # branch quietly accumulating backdated entries; it is not meant to bind
    # the people the escalation summons. Without this, a backlog past the
    # ceiling could not be cleared by anyone at all.
    UNRESTRICTED_ROLES = ('REGIONAL_MANAGER', 'BELT_MANAGER', 'SUPER_ADMIN')

    @classmethod
    def can_recover(cls, branch, actor=None) -> dict:
        """
        Whether the given actor may recover unaided.

        A branch manager is capped at MAX_BM_RECOVERY_DAYS. Regional
        managers and above are not — they are who the cap escalates to.

        Returns:
            {'allowed': bool, 'stranded_count': int, 'requires_rm': bool}
        """
        stranded = cls.get_stranded_sheets(branch)
        count = len(stranded)

        role = getattr(getattr(actor, 'role', None), 'name', None)
        unrestricted = role in cls.UNRESTRICTED_ROLES

        over_ceiling = count > cls.MAX_BM_RECOVERY_DAYS
        requires_rm  = over_ceiling and not unrestricted

        return {
            'allowed'        : count > 0 and not requires_rm,
            'stranded_count' : count,
            'requires_rm'    : requires_rm,
        }

    @classmethod
    def get_recovery_context(cls, sheet) -> dict:
        """
        Everything the recovery form needs to show before the manager
        enters anything: what the system already knows about the day.

        expected_cash is computed the same way CashierFloat.compute_variance
        does, so the figure shown before entry matches the one the sign-off
        will validate against.
        """
        from apps.finance.models import CashierFloat, PettyCash, Receipt
        from apps.finance.sheet_engine import SheetEngine
        from apps.accounts.models import CustomUser
        from apps.jobs.models import Job

        existing_float = CashierFloat.objects.filter(
            daily_sheet = sheet,
        ).select_related('cashier').first()

        if existing_float:
            cashier = existing_float.cashier
            opening = existing_float.opening_float
        else:
            cashier = CustomUser.objects.filter(
                branch     = sheet.branch,
                role__name = 'CASHIER',
                is_active  = True,
            ).first()
            opening = SheetEngine.DEFAULT_FLOAT_AMOUNT

        cash_collected = Decimal('0.00')
        petty_out      = Decimal('0.00')

        if cashier:
            cash_collected = Receipt.objects.filter(
                daily_sheet    = sheet,
                cashier        = cashier,
                payment_method = 'CASH',
                is_void        = False,
            ).aggregate(t=Sum('amount_paid'))['t'] or Decimal('0.00')

            if existing_float:
                petty_out = PettyCash.objects.filter(
                    daily_sheet   = sheet,
                    cashier_float = existing_float,
                ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        all_receipts = Receipt.objects.filter(
            daily_sheet = sheet,
            is_void     = False,
        ).aggregate(t=Sum('amount_paid'))['t'] or Decimal('0.00')

        return {
            'sheet_id'          : sheet.pk,
            'date'              : sheet.date,
            'cashier_id'        : cashier.pk if cashier else None,
            'cashier_name'      : cashier.full_name if cashier else None,
            'has_float'         : existing_float is not None,
            'float_id'          : existing_float.pk if existing_float else None,
            # A sheet can strand with its float already signed: the cashier
            # counted, signed and went home, and only the close never
            # happened. The form must then confirm her figure rather than
            # ask for a fresh count, or it invites a number that recovery
            # will refuse and that nobody physically counted.
            'is_signed_off'     : bool(existing_float and existing_float.is_signed_off),
            'signed_closing'    : existing_float.closing_cash if existing_float and existing_float.is_signed_off else None,
            'signed_off_at'     : existing_float.signed_off_at if existing_float and existing_float.is_signed_off else None,
            'signed_variance'   : existing_float.variance if existing_float and existing_float.is_signed_off else None,
            'suggested_opening' : opening,
            'cash_collected'    : cash_collected,
            'petty_cash_out'    : petty_out,
            'expected_cash'     : opening + cash_collected - petty_out,
            'total_revenue'     : all_receipts,
            'job_count'         : Job.objects.filter(daily_sheet=sheet).count(),
        }

    # ── Write side ────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def recover_sheet(
        cls,
        sheet,
        opening_float: Decimal,
        closing_cash: Decimal,
        reason: str,
        notes: str,
        recovered_by,
        reconciled_with,
        variance_notes: str = '',
    ) -> dict:
        """
        Recover a single stranded sheet.

        One day per call, deliberately. Closing a sheet stages the next
        day's float, so recoveries are inherently sequential; batching
        them would hide that ordering and leave a half-finished state if
        a later day failed after an earlier one had committed.

        Args:
            sheet           : the stranded DailySalesSheet
            opening_float   : what the cashier physically started with
            closing_cash    : what was physically counted, per the
                              reconciliation with the cashier
            reason          : DailySalesSheet.RecoveryReason value
            notes           : mandatory explanation
            recovered_by    : the manager keying the entry
            reconciled_with : the cashier who counted the cash
            variance_notes  : required if the count does not tally

        Returns:
            {'ok': True, 'sheet': sheet, 'variance': Decimal}
            {'ok': False, 'error': str}
        """
        from apps.finance.models import CashierFloat, DailySalesSheet
        from apps.finance.float_engine import FloatEngine
        from apps.finance.sheet_engine import SheetEngine

        if sheet.status != DailySalesSheet.Status.OPEN:
            return {'ok': False, 'error': f'Sheet is already {sheet.status}.'}

        if sheet.date >= timezone.localdate():
            return {
                'ok': False,
                'error': 'Only sheets from before today can be recovered.',
            }

        if not notes.strip():
            return {'ok': False, 'error': 'An explanation is required.'}

        if reason not in DailySalesSheet.RecoveryReason.values:
            return {'ok': False, 'error': 'Invalid recovery reason.'}

        gate = cls.can_recover(sheet.branch, actor=recovered_by)
        if gate['requires_rm']:
            return {
                'ok': False,
                'error': (
                    f"{gate['stranded_count']} days are unclosed. A regional "
                    f"manager must intervene before these can be recovered."
                ),
            }

        opening_float = Decimal(str(opening_float))
        closing_cash  = Decimal(str(closing_cash))

        # Stage a float if the day never had one, then link it. Both are
        # no-ops from the cashier's point of view — the cash was physically
        # held regardless of whether the system recorded it.
        float_record = CashierFloat.objects.filter(daily_sheet=sheet).first()

        if not float_record:
            staged = FloatEngine.stage_float(
                cashier     = reconciled_with,
                amount      = opening_float,
                set_by      = recovered_by,
                target_date = sheet.date,
                branch      = sheet.branch,
            )
            if not staged['ok']:
                return {'ok': False, 'error': staged['error']}

            FloatEngine.link_staged_floats(sheet)
            float_record = CashierFloat.objects.filter(daily_sheet=sheet).first()

            if not float_record:
                return {
                    'ok': False,
                    'error': 'Float was staged but could not be linked to the sheet.',
                }
        elif float_record.opening_float != opening_float:
            # The manager corrected the opening figure during reconciliation.
            float_record.opening_float = opening_float
            float_record.save(update_fields=['opening_float', 'updated_at'])

                # A sheet can strand with its float already signed: the cashier
        # counted, signed and went home, and only the close never happened.
        # That is a completed step, not a conflict — the day still needs
        # closing, and refusing here leaves it stranded forever.
        #
        # The cashier's own figure stands. It is not rewritten with a
        # number the manager keyed weeks later, and a disagreement is a
        # conversation between two people rather than something to
        # silently resolve in favour of whoever opened the modal.
        already_signed = float_record.is_signed_off
        if already_signed:
            if float_record.closing_cash != closing_cash:
                return {
                    'ok': False,
                    'error': (
                        f'{reconciled_with.full_name} signed this shift off at '
                        f'GHS {float_record.closing_cash}. Enter that figure to '
                        f'close the day, or speak to her if it is wrong — a '
                        f'signed count is not overwritten from here.'
                    ),
                }

        if not already_signed:
            shift_notes = (
                f'Recovered on {timezone.localdate():%d %b %Y} by '
                f'{recovered_by.full_name}. Cash physically counted and '
                f'reconciled with {reconciled_with.full_name}. '
                f'Reason: {DailySalesSheet.RecoveryReason(reason).label}. {notes}'
            )

            signed = FloatEngine.sign_off(
                float_record   = float_record,
                closing_cash   = closing_cash,
                breakdown      = {},
                variance_notes = variance_notes,
                shift_notes    = shift_notes,
                signed_off_by  = recovered_by,
            )
            if not signed['ok']:
                return {'ok': False, 'error': signed['error']}

            # The manager keyed a figure the cashier did not sign, so the
            # entry is marked as recovered and carries who it was counted
            # with. A shift the cashier signed herself is neither.
            float_record.is_recovery_entry = True
            float_record.reconciled_with   = reconciled_with
            float_record.save(update_fields=[
                'is_recovery_entry', 'reconciled_with', 'updated_at',
            ])

        # auto=True is what stages the following day's float, which is the
        # whole point of the recovery — it unblocks the next stranded day.
        engine = SheetEngine(sheet.branch)
        engine.close_sheet(sheet, closed_by=recovered_by, auto=True)

        sheet.refresh_from_db()
        sheet.recovery_reason = reason
        sheet.recovery_notes  = notes
        sheet.recovered_by    = recovered_by
        sheet.recovered_at    = timezone.now()
        sheet.save(update_fields=[
            'recovery_reason', 'recovery_notes',
            'recovered_by', 'recovered_at', 'updated_at',
        ])

                # Read from the float rather than from the sign-off result: on a
        # shift the cashier signed herself there was no sign-off call in
        # this run, and the variance she recorded is the one that counts.
        float_record.refresh_from_db()
        variance = float_record.variance or Decimal('0.00')

        cls._notify_rm_recovered(sheet, recovered_by, variance)

        logger.info(
            'RecoveryService: sheet %s (%s) recovered by %s — variance GHS %s',
            sheet.pk, sheet.date, recovered_by.full_name, variance,
        )

        return {'ok': True, 'sheet': sheet, 'variance': variance}

    # ── Notifications ─────────────────────────────────────────

    @classmethod
    def _notify_rm_recovered(cls, sheet, recovered_by, variance) -> None:
        """Regional manager is told of every recovery, with its reason."""
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            region = getattr(sheet.branch, 'region', None)
            if not region:
                return

            label = sheet.branch.code
            rms = CustomUser.objects.filter(
                region     = region,
                role__name = 'REGIONAL_MANAGER',
                is_active  = True,
            )
            for rm in rms:
                notify(
                    recipient = rm,
                    verb      = 'SHEET_RECOVERED',
                    message   = (
                        f'{recovered_by.full_name} recovered the {sheet.date:%d %b} '
                        f'sheet at {label} — closed retrospectively with a variance '
                        f'of GHS {variance}.'
                    ),
                    link      = '/portal/regional-manager/',
                )
        except Exception:
            logger.exception(
                'RecoveryService: failed to notify RM of recovery for sheet %s',
                sheet.pk,
            )