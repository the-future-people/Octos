# apps/jobs/services/cashier_service.py
"""
Cashier services — command-side operations for payment confirmation.

confirm_payment() is the single entry point for the cashier payment flow:
  1. Calculate amount paid from deposit percentage
  2. Validate split legs sum
  3. Persist payment fields on job
  4. Advance FSM to COMPLETE
  5. Issue receipt (with PaymentLeg records for SPLIT)
  6. Handle partial credit if supplied

Returns a result dict ready for the API response.
Raises ValueError on validation failures (caller returns 400).
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def confirm_payment(job, validated_data: dict, actor) -> dict:
    """
    Execute the full cashier payment confirmation flow.

    Args:
        job            : Job instance in PENDING_PAYMENT status
        validated_data : dict from CashierPaymentSerializer.validated_data
        actor          : CustomUser (the cashier)

    Returns:
        dict — result payload for the API response

    Raises:
        ValueError      — split legs mismatch, FSM rejection
        PermissionError — FSM permission check
    """
    from apps.jobs.status_engine import JobStatusEngine
    from apps.jobs.models import Job

    deposit_pct    = validated_data['deposit_percentage']
    notes          = validated_data.get('notes', '')
    payment_method = validated_data.get('payment_method', 'CASH')
    split_legs     = validated_data.get('split_legs', [])

    # ── Calculate amount paid ─────────────────────────────────────────
    if job.estimated_cost:
        amount_paid = (job.estimated_cost * deposit_pct) / 100
    else:
        amount_paid = None

    # ── Validate split legs sum ───────────────────────────────────────
    if payment_method == 'SPLIT' and split_legs:
        legs_total = sum(float(leg['amount']) for leg in split_legs)
        if amount_paid and abs(legs_total - float(amount_paid)) > 0.01:
            raise ValueError(
                f'Split legs total (GHS {legs_total:.2f}) must equal '
                f'amount due (GHS {float(amount_paid):.2f}).'
            )

    # ── Persist payment fields on job ─────────────────────────────────
    job.deposit_percentage = deposit_pct
    job.amount_paid        = amount_paid
    job.payment_method     = 'SPLIT' if payment_method == 'SPLIT' else payment_method
    job.momo_reference     = validated_data.get('momo_reference', '')
    job.pos_approval_code  = validated_data.get('pos_approval_code', '')
    job.cash_tendered      = validated_data.get('cash_tendered')
    job.change_given       = validated_data.get('change_given')
    job.save(update_fields=[
        'deposit_percentage', 'amount_paid',
        'payment_method', 'momo_reference',
        'pos_approval_code', 'cash_tendered',
        'change_given', 'updated_at',
    ])

    # ── Advance FSM to COMPLETE ───────────────────────────────────────
    result = JobStatusEngine.advance(
        job       = job,
        to_status = Job.COMPLETE,
        actor     = actor,
        notes     = notes or f"Payment confirmed: {deposit_pct}% deposit",
    )

    result['deposit_percentage'] = deposit_pct
    result['amount_paid']        = str(amount_paid) if amount_paid else None
    result['balance_due']        = str(job.balance_due) if job.balance_due else '0.00'
    result['payment_method']     = payment_method

    # ── Issue receipt ─────────────────────────────────────────────────
    _issue_receipt(job, validated_data, actor, payment_method, split_legs, amount_paid, result)

    # ── Partial credit ────────────────────────────────────────────────
    _handle_partial_credit(job, validated_data, result)

    return result


# ── Private helpers ───────────────────────────────────────────────────────────

def _issue_receipt(job, validated_data, actor, payment_method, split_legs, amount_paid, result):
    """Issue a receipt and attach receipt info to result dict. Never raises."""
    try:
        from apps.finance.receipt_engine import ReceiptEngine
        from apps.finance.models import DailySalesSheet, PaymentLeg

        daily_sheet = DailySalesSheet.objects.filter(
            branch=job.branch,
            status=DailySalesSheet.Status.OPEN,
        ).order_by('-date').first()

        if not daily_sheet:
            result['receipt_number'] = None
            result['receipt_id']     = None
            return

        engine = ReceiptEngine(job.branch)

        if payment_method == 'SPLIT' and split_legs:
            receipt = engine.issue(
                job            = job,
                cashier        = actor,
                daily_sheet    = daily_sheet,
                payment_method = 'SPLIT',
                amount_paid    = amount_paid,
                balance_due    = job.balance_due or 0,
                customer_phone = validated_data.get('customer_phone', ''),
                company_name   = validated_data.get('company_name', ''),
                split_legs     = split_legs,
            )
            for i, leg in enumerate(split_legs, 1):
                PaymentLeg.objects.create(
                    job               = job,
                    receipt           = receipt,
                    payment_method    = leg['method'],
                    amount            = leg['amount'],
                    momo_reference    = leg.get('reference', '') if leg['method'] == 'MOMO' else '',
                    pos_approval_code = leg.get('reference', '') if leg['method'] == 'POS'  else '',
                    sequence          = i,
                )
        else:
            receipt = engine.issue(
                job               = job,
                cashier           = actor,
                daily_sheet       = daily_sheet,
                payment_method    = payment_method,
                amount_paid       = amount_paid,
                balance_due       = job.balance_due or 0,
                momo_reference    = validated_data.get('momo_reference', ''),
                pos_approval_code = validated_data.get('pos_approval_code', ''),
                customer_phone    = validated_data.get('customer_phone', ''),
                company_name      = validated_data.get('company_name', ''),
            )

        result['receipt_number'] = receipt.receipt_number
        result['receipt_id']     = receipt.id

    except Exception as e:
        logger.error(f"ReceiptEngine failed: {e}", exc_info=True)
        result['receipt_number'] = None
        result['receipt_id']     = None


def _handle_partial_credit(job, validated_data, result):
    """Apply partial credit to the job if supplied. Never raises."""
    partial_credit_amount     = validated_data.get('partial_credit_amount')
    partial_credit_account_id = validated_data.get('partial_credit_account')

    if not (partial_credit_amount and partial_credit_account_id):
        return

    try:
        from apps.finance.models import CreditAccount, DailySalesSheet
        from apps.customers.credit_engine import CreditEngine
        from django.db.models import F

        credit_account = CreditAccount.objects.get(pk=partial_credit_account_id)
        sheet = DailySalesSheet.objects.filter(
            branch=job.branch, status='OPEN'
        ).order_by('-date').first()

        if not sheet:
            return

        credit_amount = Decimal(str(partial_credit_amount))
        CreditEngine.check_eligibility(credit_account, credit_amount)

        credit_account.current_balance += credit_amount
        credit_account.save(update_fields=['current_balance', 'updated_at'])

        DailySalesSheet.objects.filter(pk=sheet.pk).update(
            total_credit_issued=F('total_credit_issued') + credit_amount
        )

        job.partial_credit_amount  = credit_amount
        job.partial_credit_account = credit_account
        job.save(update_fields=[
            'partial_credit_amount', 'partial_credit_account', 'updated_at'
        ])

        result['partial_credit_amount']  = str(credit_amount)
        result['partial_credit_account'] = credit_account.id

    except Exception as e:
        logger.error(f"Partial credit failed: {e}", exc_info=True)