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
from apps.core.broadcast import broadcast_invalidation

logger = logging.getLogger(__name__)


def confirm_payment(job, validated_data: dict, actor) -> dict:
    from apps.jobs.status_engine import JobStatusEngine
    from apps.jobs.models import Job

    deposit_pct    = validated_data['deposit_percentage']
    notes          = validated_data.get('notes', '')
    payment_method = validated_data.get('payment_method', 'CASH')
    split_legs     = validated_data.get('split_legs', [])

    # ── Full credit payment (Mr. Doodoo flow) ─────────────────────────
    if payment_method == 'CREDIT':
        return _handle_full_credit(job, validated_data, actor, notes)

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

    # ── Wallet credit (cashier + customer chose to save overpayment
    # instead of taking cash change) — must run before change_given is
    # persisted, since a GHS 200 cap can force part of the request back
    # to cash. Never silently short-changes the customer. ─────────────
    wallet_extra    = {}
    change_given_val = validated_data.get('change_given')
    wallet_credit_amount = validated_data.get('wallet_credit_amount')

    if wallet_credit_amount:
        wallet_extra = _apply_wallet_credit(
            job              = job,
            requested_amount = wallet_credit_amount,
            wallet_consent   = validated_data.get('wallet_consent'),
            actor            = actor,
        )
        overflow = wallet_extra.pop('_overflow', Decimal('0'))
        if overflow > 0 and change_given_val is not None:
            change_given_val = Decimal(str(change_given_val)) + overflow

    # ── Wallet redemption (payment_method=WALLET — customer is paying
    # for THIS job using existing wallet balance instead of cash) ─────
    if payment_method == 'WALLET':
        wallet_extra.update(
            _redeem_wallet_credit(job=job, actor=actor)
        )

    # ── Persist payment fields on job ─────────────────────────────────
    job.deposit_percentage = deposit_pct
    job.amount_paid        = amount_paid
    job.payment_method     = 'SPLIT' if payment_method == 'SPLIT' else payment_method
    job.momo_reference     = validated_data.get('momo_reference', '')
    job.pos_approval_code  = validated_data.get('pos_approval_code', '')
    job.cash_tendered      = validated_data.get('cash_tendered')
    job.change_given       = change_given_val
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

    # ── Lifecycle axes ────────────────────────────────────────────────
    _apply_payment_axes(job, actor)

    # ── Issue receipt ─────────────────────────────────────────────────
    _issue_receipt(job, validated_data, actor, payment_method, split_legs, amount_paid, result)

    # ── Partial credit ────────────────────────────────────────────────────────
    _handle_partial_credit(job, validated_data, result)

    if wallet_extra:
        result.update(wallet_extra)

    broadcast_invalidation(job.branch.id, [
        'paymentQueue', 'cashierSummary', 'shiftStatus',
        'todaySummary', 'jobStats', 'recentJobs',
        'jobs', 'attendant-my-jobs', 'attendant-my-jobs-recent',
    ])

    return result

# ── Private helpers ───────────────────────────────────────────────────────────
def _apply_payment_axes(job, actor):
    """
    Writes the lifecycle axes after a payment lands.

    Payment state reads amounts, never the deposit percentage — a 100%
    tier on a job whose cost later changed is not evidence of settlement.
    This mirrors the backfill migration's rule exactly.

    Instant work is finished before the cashier ever sees it and the
    customer leaves with it in hand, so a counter sale closes all three
    axes at once: SETTLED / DONE / HANDED_OVER. Production and design
    jobs move their work and handover axes elsewhere, by the people who
    own them.
    """
    from django.utils import timezone
    from apps.jobs.models import JobStatusLog

    paid = job.amount_paid or Decimal('0')
    cost = job.estimated_cost or Decimal('0')

    if cost > 0 and paid >= cost:
        payment_state = 'SETTLED'
    elif paid > 0:
        payment_state = 'DEPOSIT_PAID'
    else:
        payment_state = 'UNPAID'

    fields = []
    now    = timezone.now()

    if job.payment_state != payment_state:
        JobStatusLog.objects.create(
            job             = job,
            axis            = JobStatusLog.Axis.PAYMENT,
            from_status     = job.payment_state,
            to_status       = payment_state,
            actor           = actor,
            notes           = 'Payment confirmed at the counter.',
            transitioned_at = now,
        )
        job.payment_state = payment_state
        fields.append('payment_state')

    if job.job_type == 'INSTANT' and payment_state == 'SETTLED':
        if job.work_state != 'DONE':
            JobStatusLog.objects.create(
                job             = job,
                axis            = JobStatusLog.Axis.WORK,
                from_status     = job.work_state,
                to_status       = 'DONE',
                actor           = actor,
                notes           = 'Instant job — work completed before payment.',
                transitioned_at = now,
            )
            job.work_state = 'DONE'
            fields.append('work_state')

        if job.handover_state != 'HANDED_OVER':
            JobStatusLog.objects.create(
                job             = job,
                axis            = JobStatusLog.Axis.HANDOVER,
                from_status     = job.handover_state,
                to_status       = 'HANDED_OVER',
                actor           = actor,
                notes           = 'Counter sale — collected at payment.',
                transitioned_at = now,
            )
            job.handover_state  = 'HANDED_OVER'
            job.handed_over_at  = now
            job.handed_over_by  = actor
            fields += ['handover_state', 'handed_over_at', 'handed_over_by']

    if fields:
        job.save(update_fields=fields + ['updated_at'])


def _handle_full_credit(job, validated_data, actor, notes):
    """
    Full credit payment flow — amount_paid=0, full job value
    goes onto the customer's credit account.
    Used when payment_method=CREDIT with no partial cash component.
    """
    from apps.jobs.status_engine import JobStatusEngine
    from apps.jobs.models import Job
    from apps.finance.models import CreditAccount, DailySalesSheet
    from apps.finance.credit_engine import CreditEngine
    from django.db.models import F

    credit_account_id = validated_data.get('credit_account_id')
    if not credit_account_id:
        raise ValueError('Credit account is required for full credit payment.')

    try:
        credit_account = CreditAccount.objects.get(pk=credit_account_id)
    except CreditAccount.DoesNotExist:
        raise ValueError('Credit account not found.')

    credit_amount = job.estimated_cost or Decimal('0')
    if credit_amount <= 0:
        raise ValueError('Job has no estimated cost — cannot issue credit.')

    # Check credit limit
    engine = CreditEngine(credit_account)
    engine.check_or_raise(credit_amount)

    # Get today's sheet
    sheet = DailySalesSheet.objects.filter(
        branch=job.branch,
        status=DailySalesSheet.Status.OPEN,
    ).order_by('-date').first()
    if not sheet:
        raise ValueError('No open sheet — cannot process credit payment.')

    # Persist payment fields — amount_paid=0 for full credit
    job.deposit_percentage = 100
    job.amount_paid        = Decimal('0.00')
    job.payment_method     = 'CREDIT'
    job.credit_account     = credit_account
    job.save(update_fields=[
        'deposit_percentage', 'amount_paid',
        'payment_method', 'credit_account', 'updated_at',
    ])

    # Issue credit against the account
    engine.issue_credit(
        job         = job,
        amount      = credit_amount,
        actor       = actor,
        daily_sheet = sheet,
    )

    # Update sheet credit issued total
    DailySalesSheet.objects.filter(pk=sheet.pk).update(
        total_credit_issued=F('total_credit_issued') + credit_amount
    )

    # Advance FSM to COMPLETE
    result = JobStatusEngine.advance(
        job       = job,
        to_status = Job.COMPLETE,
        actor     = actor,
        notes     = notes or f"Full credit — GHS {credit_amount} charged to {credit_account.customer.full_name}",
    )

    result['deposit_percentage'] = 100
    result['amount_paid']        = '0.00'
    result['balance_due']        = '0.00'
    result['payment_method']     = 'CREDIT'
    result['credit_amount']      = str(credit_amount)

    # Full credit means nothing has been paid — the balance sits on the
    # account. Payment state stays UNPAID, which is the honest reading,
    # and the work is released against the credit agreement rather than
    # against settlement.
    _apply_payment_axes(job, actor)

    # Issue receipt with CREDIT payment method
    _issue_receipt(job, validated_data, actor, 'CREDIT', [], Decimal('0.00'), result)

    return result

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
        from apps.finance.credit_engine import CreditEngine
        from django.db.models import F

        credit_account = CreditAccount.objects.get(pk=partial_credit_account_id)
        sheet = DailySalesSheet.objects.filter(
            branch=job.branch, status='OPEN'
        ).order_by('-date').first()

        if not sheet:
            return

        credit_amount = Decimal(str(partial_credit_amount))
        engine = CreditEngine(credit_account)
        engine.check_or_raise(credit_amount)

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


def _apply_wallet_credit(job, requested_amount, wallet_consent, actor):
    """
    Applies job-redeemable wallet credit from an overpayment. Unlike
    _handle_partial_credit, this deliberately RAISES on real problems
    (missing customer, missing consent) rather than silently swallowing
    them — consent and eligibility are the fraud-resistance mechanisms
    this feature exists to enforce, so a failure here must surface to
    the cashier, not vanish into a log line.

    Caps the customer's wallet_balance at GHS 200. Any amount beyond
    the cap is reported back via '_overflow' so the caller can route
    it back into cash change instead of losing it.
    """
    from django.db import transaction
    from django.utils import timezone
    from apps.customers.models import CustomerProfile
    from apps.finance.models import CustomerWalletTransaction
    from apps.accounts.models import CustomUser
    from apps.notifications.services import notify

    if not job.customer_id:
        raise ValueError(
            'Wallet credit requires a registered customer — walk-ins are not eligible.'
        )
    if not wallet_consent:
        raise ValueError('Customer consent is required before adding wallet credit.')

    requested = Decimal(str(requested_amount))
    if requested <= 0:
        return {}

    WALLET_CAP = Decimal('200.00')

    with transaction.atomic():
        customer = CustomerProfile.objects.select_for_update().get(pk=job.customer_id)

        headroom = WALLET_CAP - customer.wallet_balance
        if headroom <= 0:
            raise ValueError(
                f'{customer.display_name} has already reached the GHS 200 wallet limit.'
            )

        actual_credit = min(requested, headroom)
        overflow      = requested - actual_credit

        balance_before = customer.wallet_balance
        balance_after  = balance_before + actual_credit
        now = timezone.now()

        CustomerWalletTransaction.objects.create(
            customer             = customer,
            branch               = job.branch,
            job                  = job,
            transaction_type     = CustomerWalletTransaction.TransactionType.CREDIT_ADDED,
            amount               = actual_credit,
            balance_before       = balance_before,
            balance_after        = balance_after,
            recorded_by          = actor,
            consent_confirmed_at = now,
        )

        CustomerProfile.objects.filter(pk=customer.pk).update(
            wallet_balance           = balance_after,
            wallet_last_activity_at  = now,
        )

    result = {
        'wallet_credit_added': str(actual_credit),
        'wallet_balance':      str(balance_after),
        '_overflow':           overflow,
    }
    if overflow > 0:
        result['wallet_credit_capped_overflow'] = str(overflow)

    try:
        bm = CustomUser.objects.filter(
            branch=job.branch, role__name='BRANCH_MANAGER',
        ).exclude(pk=actor.pk).first()
        if bm:
            notify(
                recipient = bm,
                verb      = 'system',
                message   = (
                    f"{actor.full_name} added GHS {actual_credit} wallet credit "
                    f"for {customer.display_name} (job {job.job_number})."
                ),
                link      = f'/customers/{customer.id}/',
            )
    except Exception:
        logger.error('Failed to notify BM of wallet credit', exc_info=True)

    return result

def _redeem_wallet_credit(job, actor):
    """
    Redeems wallet balance against THIS job's cost. Job-only redemption
    is the entire point of this feature — there is deliberately no
    cash-redemption path anywhere in this system.
    """
    from django.db import transaction
    from django.utils import timezone
    from apps.customers.models import CustomerProfile
    from apps.finance.models import CustomerWalletTransaction
    from apps.accounts.models import CustomUser
    from apps.notifications.services import notify

    if not job.customer_id:
        raise ValueError('Wallet redemption requires a registered customer.')

    job_cost = job.estimated_cost or Decimal('0')
    if job_cost <= 0:
        raise ValueError('Job has no cost — nothing to redeem against.')

    with transaction.atomic():
        customer = CustomerProfile.objects.select_for_update().get(pk=job.customer_id)

        if customer.wallet_balance < job_cost:
            raise ValueError(
                f'{customer.display_name} has GHS {customer.wallet_balance} in wallet '
                f'credit — not enough to cover GHS {job_cost}.'
            )

        balance_before = customer.wallet_balance
        balance_after  = balance_before - job_cost
        now = timezone.now()

        CustomerWalletTransaction.objects.create(
            customer         = customer,
            branch           = job.branch,
            job              = job,
            transaction_type = CustomerWalletTransaction.TransactionType.REDEEMED_JOB,
            amount           = job_cost,
            balance_before   = balance_before,
            balance_after    = balance_after,
            recorded_by      = actor,
        )

        CustomerProfile.objects.filter(pk=customer.pk).update(
            wallet_balance          = balance_after,
            wallet_last_activity_at = now,
        )

    result = {
        'wallet_redeemed':      str(job_cost),
        'wallet_balance_after': str(balance_after),
    }

    try:
        bm = CustomUser.objects.filter(
            branch=job.branch, role__name='BRANCH_MANAGER',
        ).exclude(pk=actor.pk).first()
        if bm:
            notify(
                recipient = bm,
                verb      = 'system',
                message   = (
                    f"{actor.full_name} redeemed GHS {job_cost} wallet credit "
                    f"for {customer.display_name} (job {job.job_number})."
                ),
                link      = f'/customers/{customer.id}/',
            )
    except Exception:
        logger.error('Failed to notify BM of wallet redemption', exc_info=True)

    return result