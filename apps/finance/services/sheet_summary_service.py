# apps/finance/services/sheet_summary_service.py
"""
SheetSummaryService
===================
Single source of truth for the day sheet summary payload.
Used by the BM portal day sheet view and the /summary/ endpoint.

Responsibilities:
- Live revenue computation for open sheets (delegates to revenue_selectors)
- Frozen total reads for closed sheets (direct model fields)
- Job stats: total, complete, pending, routed, registered, walkin
- Registration rate and pace (jobs/hr)
- Inventory snapshot (delegates to InventoryEngine)
- Alerts: outstanding payments, low stock flags

NOT responsible for:
- Cashier float internals (EODService owns that)
- Petty cash detail (EODService owns that)
- Credit sales detail (EODService owns that)
- Pre-close checklist logic (EODService owns that)
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


class SheetSummaryService:

    @staticmethod
    def get_summary(sheet, branch) -> dict:
        """
        Build the unified day sheet summary.

        Args:
            sheet  : DailySalesSheet instance
            branch : Branch instance

        Returns:
            dict with keys: meta, revenue, jobs, registration, pace,
                            inventory, alerts
        """
        from apps.finance.models import DailySalesSheet

        is_open = sheet.status == DailySalesSheet.Status.OPEN

        meta        = SheetSummaryService._build_meta(sheet, branch)
        revenue     = SheetSummaryService._build_revenue(sheet, branch, is_open)
        jobs        = SheetSummaryService._build_jobs(sheet, branch)
        registration = SheetSummaryService._build_registration(jobs)
        pace        = SheetSummaryService._build_pace(sheet, jobs, is_open)
        inventory   = SheetSummaryService._build_inventory(branch, sheet)
        alerts      = SheetSummaryService._build_alerts(jobs, inventory, sheet, is_open)

        return {
            'meta'        : meta,
            'revenue'     : revenue,
            'jobs'        : jobs,
            'registration': registration,
            'pace'        : pace,
            'inventory'   : inventory,
            'alerts'      : alerts,
        }

    # ── Meta ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_meta(sheet, branch) -> dict:
        return {
            'sheet_id'           : sheet.pk,
            'sheet_number'       : sheet.sheet_number or f"#{sheet.pk}",
            'date'               : sheet.date.isoformat(),
            'status'             : sheet.status,
            'branch'             : branch.name,
            'branch_code'        : branch.code,
            'opened_at'          : sheet.opened_at.isoformat() if sheet.opened_at else None,
            'opened_by'          : sheet.opened_by.full_name if sheet.opened_by else 'System',
            'closed_at'          : sheet.closed_at.isoformat() if sheet.closed_at else None,
            'closed_by'          : sheet.closed_by.full_name if sheet.closed_by else None,
            'is_public_holiday'  : sheet.is_public_holiday,
            'public_holiday_name': sheet.public_holiday_name,
            'notes'              : sheet.notes,
        }

    # ── Revenue ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_revenue(sheet, branch, is_open: bool) -> dict:
        """
        Live computation for open sheets.
        Frozen field reads for closed sheets.
        Single source of truth — no duplication with DailySalesSheetTodayView.
        """
        if is_open:
            return SheetSummaryService._live_revenue(sheet)
        return SheetSummaryService._frozen_revenue(sheet)

    @staticmethod
    def _live_revenue(sheet) -> dict:
        """
        Compute revenue live from completed jobs + payment legs.
        Delegates SPLIT aggregation to revenue_selectors — no duplication.
        """
        from apps.jobs.models import Job
        from apps.jobs.selectors.revenue_selectors import get_method_total
        from django.db.models import Sum

        completed = Job.objects.filter(
            daily_sheet  = sheet,
            status       = Job.COMPLETE,
            amount_paid__isnull=False,
        )

        cash  = get_method_total(completed, 'CASH')
        momo  = get_method_total(completed, 'MOMO')
        pos   = get_method_total(completed, 'POS')
        total = cash + momo + pos

        credit_issued = Job.objects.filter(
            daily_sheet    = sheet,
            status         = Job.COMPLETE,
            payment_method = 'CREDIT',
        ).aggregate(t=Sum('amount_paid'))['t'] or Decimal('0')

        petty_out      = sheet.total_petty_cash_out or Decimal('0')
        credit_settled = sheet.total_credit_settled or Decimal('0')
        net_cash       = cash + credit_settled - petty_out

        return {
            'cash'            : str(cash),
            'momo'            : str(momo),
            'pos'             : str(pos),
            'total'           : str(total),
            'credit_issued'   : str(credit_issued),
            'credit_settled'  : str(credit_settled),
            'petty_cash_out'  : str(petty_out),
            'net_cash_in_till': str(net_cash),
            'is_live'         : True,
        }

    @staticmethod
    def _frozen_revenue(sheet) -> dict:
        """Read frozen totals from closed sheet — never recomputed."""
        cash  = sheet.total_cash  or Decimal('0')
        momo  = sheet.total_momo  or Decimal('0')
        pos   = sheet.total_pos   or Decimal('0')
        total = cash + momo + pos

        return {
            'cash'            : str(cash),
            'momo'            : str(momo),
            'pos'             : str(pos),
            'total'           : str(total),
            'credit_issued'   : str(sheet.total_credit_issued  or 0),
            'credit_settled'  : str(sheet.total_credit_settled or 0),
            'petty_cash_out'  : str(sheet.total_petty_cash_out or 0),
            'net_cash_in_till': str(sheet.net_cash_in_till     or 0),
            'is_live'         : False,
        }

    # ── Jobs ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_jobs(sheet, branch) -> dict:
        """
        Job counts scoped to this sheet.
        registered = linked to a customer
        walkin     = no customer linked
        """
        from apps.jobs.models import Job

        qs = Job.objects.filter(daily_sheet=sheet)

        total      = qs.count()
        complete   = qs.filter(status=Job.COMPLETE).count()
        in_progress= qs.filter(status=Job.IN_PROGRESS).count()
        pending    = qs.filter(status=Job.PENDING_PAYMENT).count()
        cancelled  = qs.filter(status='CANCELLED').count()
        routed     = qs.filter(is_routed=True).count()
        registered = qs.exclude(customer__isnull=True).count()
        walkin     = total - registered

        return {
            'total'      : total,
            'complete'   : complete,
            'in_progress': in_progress,
            'pending'    : pending,
            'cancelled'  : cancelled,
            'routed'     : routed,
            'registered' : registered,
            'walkin'     : walkin,
        }

    # ── Registration ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_registration(jobs: dict) -> dict:
        total      = jobs['total']
        registered = jobs['registered']
        walkin     = jobs['walkin']
        rate       = round(registered / total * 100) if total > 0 else 0

        return {
            'registered': registered,
            'walkin'    : walkin,
            'rate'      : rate,
            'label'     : f"{rate}% of jobs linked to a customer",
        }

    # ── Pace ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_pace(sheet, jobs: dict, is_open: bool) -> dict:
        """
        Jobs per hour since sheet opened.
        Only meaningful for open sheets — returns None for closed.
        """
        if not is_open or not sheet.opened_at:
            return {
                'jobs_per_hour': None,
                'hours_open'   : None,
            }

        from django.utils import timezone
        now        = timezone.now()
        delta      = now - sheet.opened_at
        hours_open = max(delta.total_seconds() / 3600, 0.25)  # min 15 mins
        jobs_per_hr= round(jobs['total'] / hours_open, 1)

        return {
            'jobs_per_hour': jobs_per_hr,
            'hours_open'   : round(hours_open, 1),
        }

    # ── Inventory ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_inventory(branch, sheet) -> list:
        """
        Single inventory call — replaces the two-API client-side join.
        Delegates entirely to InventoryEngine.
        Returns [] on failure — never crashes the summary.
        """
        try:
            from apps.inventory.inventory_engine import InventoryEngine
            snapshot = InventoryEngine(branch).generate_daily_snapshot(sheet.date)
            return snapshot.get('items', [])
        except Exception:
            logger.exception(
                'SheetSummaryService: inventory snapshot failed for sheet %s',
                sheet.pk,
            )
            return []

    # ── Alerts ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_alerts(jobs: dict, inventory: list, sheet, is_open: bool) -> list:
        """
        Outstanding flags the BM needs to act on.
        Only meaningful for open sheets.
        """
        alerts = []

        if not is_open:
            return alerts

        # Pending payments
        if jobs['pending'] > 0:
            count = jobs['pending']
            alerts.append({
                'type'   : 'PENDING_PAYMENTS',
                'level'  : 'warning',
                'message': (
                    f"{count} job{'s' if count != 1 else ''} still pending payment "
                    f"({jobs['in_progress']} in progress)"
                ),
            })

        # Low stock
        low_items = [
            item['consumable'] for item in inventory
            if item.get('is_low') and item.get('category') != 'Machinery'
        ]
        if low_items:
            alerts.append({
                'type'   : 'LOW_STOCK',
                'level'  : 'warning',
                'message': f"Low stock: {', '.join(low_items)}",
                'items'  : low_items,
            })

        return alerts