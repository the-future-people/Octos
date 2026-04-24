# apps/finance/services/eod_service.py

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


class EODService:

    @staticmethod
    def get_summary(sheet, branch) -> dict:
        """
        Build the full EOD summary for a daily sheet.
        Returns the complete summary dict consumed by EODSummaryView.
        """
        from django.db.models import Sum, Count
        from apps.jobs.models import Job
        from apps.finance.models import CashierFloat, PettyCash, Receipt
        from apps.accounts.models import CustomUser

        jobs = Job.objects.filter(daily_sheet=sheet).select_related(
            'intake_by', 'customer', 'assigned_to'
        )

        # ── Revenue ─────────────────────────────────────────────────────
        from apps.jobs.selectors.revenue_selectors import get_method_total
        completed_jobs_qs = jobs.filter(
            status='COMPLETE',
            amount_paid__isnull=False,
        )
        live_cash = get_method_total(completed_jobs_qs, 'CASH')
        live_momo = get_method_total(completed_jobs_qs, 'MOMO')
        live_pos  = get_method_total(completed_jobs_qs, 'POS')
        live_credit  = jobs.filter(
            status='COMPLETE',
            payment_method='CREDIT',
            amount_paid__isnull=False,
        ).aggregate(t=Sum('amount_paid'))['t'] or Decimal('0.00')
        live_petty   = sheet.total_petty_cash_out
        live_settled = sheet.total_credit_settled
        live_net     = live_cash + live_settled - live_petty

        revenue = {
            'cash'            : str(live_cash),
            'momo'            : str(live_momo),
            'pos'             : str(live_pos),
            'total'           : str(live_cash + live_momo + live_pos),
            'credit_issued'   : str(live_credit),
            'credit_settled'  : str(live_settled),
            'petty_cash_out'  : str(live_petty),
            'net_cash_in_till': str(live_net),
        }

        # ── Jobs ──────────────────────────────────────────────────────
        total_jobs     = jobs.count()
        completed_jobs = jobs.filter(status='COMPLETE').count()
        cancelled_jobs = jobs.filter(status='CANCELLED').count()
        local_jobs     = jobs.filter(is_routed=False).count()
        routed_out     = jobs.filter(is_routed=True).count()
        routed_in      = Job.objects.filter(
            assigned_to=branch,
            is_routed=True,
        ).exclude(branch=branch).count()

        pending_cashier      = jobs.filter(status='PENDING_PAYMENT')
        pending_untouched    = pending_cashier.filter(pos_transactions__isnull=True)

        def _job_rows(qs):
            rows = list(qs.values(
                'id', 'job_number', 'title', 'estimated_cost',
                'intake_by__first_name', 'intake_by__last_name', 'created_at',
            ))
            for j in rows:
                fn = j.pop('intake_by__first_name', '') or ''
                ln = j.pop('intake_by__last_name', '') or ''
                j['intake_by_name'] = f"{fn} {ln}".strip() or '—'
                j['estimated_cost'] = str(j['estimated_cost'] or 0)
                j['created_at']     = j['created_at'].isoformat() if j['created_at'] else None
            return rows

        jobs_summary = {
            'total'            : total_jobs,
            'completed'        : completed_jobs,
            'cancelled'        : cancelled_jobs,
            'local'            : local_jobs,
            'routed_out'       : routed_out,
            'routed_in'        : routed_in,
            'pending_payment'  : pending_cashier.count(),
            'pending_untouched': pending_untouched.count(),
            'pending_list'     : _job_rows(pending_cashier),
            'untouched_list'   : _job_rows(pending_untouched),
        }

        # ── Cashier activity ──────────────────────────────────────────
        floats = CashierFloat.objects.filter(
            daily_sheet=sheet
        ).select_related('cashier', 'float_set_by', 'signed_off_by')

        cashier_activity = []
        for f in floats:
            txns = Receipt.objects.filter(
                daily_sheet=sheet,
                cashier=f.cashier,
            ).order_by('created_at')

            by_method = txns.order_by().values('payment_method').annotate(
                total=Sum('amount_paid'),
                count=Count('id'),
            )
            method_breakdown = {
                row['payment_method']: {
                    'total': str(row['total'] or 0),
                    'count': row['count'],
                }
                for row in by_method
            }

            first_txn = txns.first()
            last_txn  = txns.last()

            cashier_activity.append({
                'cashier_name'     : f.cashier.full_name,
                'cashier_id'       : f.cashier.id,
                'opening_float'    : str(f.opening_float),
                'closing_cash'     : str(f.closing_cash),
                'expected_cash'    : str(f.expected_cash),
                'variance'         : str(f.variance),
                'variance_notes'   : f.variance_notes,
                'is_signed_off'    : f.is_signed_off,
                'signed_off_at'    : f.signed_off_at.isoformat() if f.signed_off_at else None,
                'float_set_at'     : f.float_set_at.isoformat() if f.float_set_at else None,
                'active_from'      : first_txn.created_at.isoformat() if first_txn else None,
                'active_to'        : last_txn.created_at.isoformat() if last_txn else None,
                'total_collected'  : str(txns.aggregate(t=Sum('amount_paid'))['t'] or 0),
                'transaction_count': txns.count(),
                'method_breakdown' : method_breakdown,
            })

        # ── Petty cash ────────────────────────────────────────────────
        petty_cash_records = PettyCash.objects.filter(
            daily_sheet=sheet
        ).select_related('recorded_by').order_by('created_at')

        petty_cash_list = list(petty_cash_records.values(
            'id', 'amount', 'purpose', 'created_at',
            'recorded_by__first_name', 'recorded_by__last_name',
        ))
        for p in petty_cash_list:
            fn = p.pop('recorded_by__first_name', '') or ''
            ln = p.pop('recorded_by__last_name', '') or ''
            p['recorded_by_name'] = f"{fn} {ln}".strip() or '—'
            p['reason']           = p.pop('purpose', '—')
            p['amount']           = str(p['amount'])
            p['created_at']       = p['created_at'].isoformat() if p['created_at'] else None

        # ── Credit sales ──────────────────────────────────────────────
        credit_jobs = jobs.filter(
            customer__credit_account__isnull=False,
            status__in=['COMPLETE', 'PENDING_PAYMENT'],
        ).select_related('customer__credit_account')

        credit_list = [
            {
                'job_number'    : j.job_number,
                'title'         : j.title,
                'estimated_cost': str(j.estimated_cost or 0),
                'customer_name' : j.customer.full_name if j.customer else '—',
            }
            for j in credit_jobs
        ]

        # ── Branch cashiers ───────────────────────────────────────────
        branch_cashiers = [
            {
                'cashier_id'  : c['id'],
                'cashier_name': f"{c['first_name']} {c['last_name']}".strip(),
            }
            for c in CustomUser.objects.filter(
                branch    =branch,
                role__name='CASHIER',
                is_active =True,
            ).values('id', 'first_name', 'last_name')
        ]

        # ── Inventory snapshot ────────────────────────────────────────
        inventory_consumption = []
        try:
            from apps.inventory.inventory_engine import InventoryEngine
            inv_snapshot = InventoryEngine(branch).generate_daily_snapshot(sheet.date)
            inventory_consumption = inv_snapshot.get('items', [])
        except Exception:
            logger.exception('EODService: daily inventory snapshot failed for sheet %s', sheet.pk)

        # ── Sheet meta ────────────────────────────────────────────────
        meta = {
            'sheet_id'           : sheet.pk,
            'sheet_number'       : sheet.sheet_number or f"#{sheet.pk}",
            'date'               : sheet.date.isoformat(),
            'status'             : sheet.status,
            'branch'             : branch.name,
            'branch_code'        : branch.code,
            'opened_at'          : sheet.opened_at.isoformat() if sheet.opened_at else None,
            'opened_by'          : sheet.opened_by.full_name if sheet.opened_by else 'System',
            'is_public_holiday'  : sheet.is_public_holiday,
            'public_holiday_name': sheet.public_holiday_name,
        }

        return {
            'meta'                 : meta,
            'revenue'              : revenue,
            'jobs'                 : jobs_summary,
            'cashier_activity'     : cashier_activity,
            'float_opened'         : floats.exists(),
            'petty_cash'           : petty_cash_list,
            'credit_sales'         : credit_list,
            'branch_cashiers'      : branch_cashiers,
            'inventory_consumption': inventory_consumption,
        }
