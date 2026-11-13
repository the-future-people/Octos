"""
Taking the balance on a deposit-paid job (13 Nov 2026).

Until now a production or design job paid by 70% deposit could never be
settled: the status engine allowed DEPOSIT_PAID -> SETTLED, but nothing made
that move, and an attendant cannot release a job that is not SETTLED.

confirm_balance() is the deposit path's smaller twin, built on its helpers
(cashier_service) so a balance behaves like any payment: the same receipt
(drawer, My shift, the WhatsApp picture), the same wallet rules, the same
payment axes. Differences:

  - only a DEPOSIT_PAID job, and only for exactly its balance_due
  - the job row is locked while it is settled, so a balance can never be
    taken twice (two cashiers, or a double tap)
  - the wallet redeems the balance, not the whole job cost
"""
import logging
from decimal import Decimal

from django.db import transaction

from apps.core.broadcast import broadcast_invalidation

logger = logging.getLogger(__name__)

METHODS = ('CASH', 'MOMO', 'POS', 'SPLIT', 'WALLET')


def check_balance_request(payment_state, balance_due, method, split_legs=None):
    """
    Whether this balance can be taken this way. Raises ValueError with words
    the cashier can act on; returns the balance as a Decimal.
    """
    if payment_state == 'SETTLED':
        raise ValueError('This job is already fully paid.')
    if payment_state != 'DEPOSIT_PAID':
        raise ValueError('Only a job with a deposit paid has a balance to take. Take its payment from the queue.')
    balance = Decimal(str(balance_due or 0)).quantize(Decimal('0.01'))
    if balance <= 0:
        raise ValueError('Nothing is owed on this job.')
    if method not in METHODS:
        raise ValueError('Take the balance by cash, MoMo, card, split, or from their wallet.')
    if method == 'SPLIT':
        legs = split_legs or []
        if len(legs) != 2:
            raise ValueError('A split payment has exactly two parts.')
        total = sum(Decimal(str(l.get('amount') or 0)) for l in legs).quantize(Decimal('0.01'))
        if total != balance:
            raise ValueError(f'The two parts (GHS {total:.2f}) must add up to the balance (GHS {balance:.2f}).')
    return balance


@transaction.atomic
def confirm_balance(job, validated_data: dict, actor) -> dict:
    from apps.jobs.models import Job
    from apps.jobs.services.cashier_service import (
        _apply_payment_axes, _apply_wallet_credit, _issue_receipt, _redeem_wallet_credit,
    )

    # Locked until this transaction ends: a second attempt waits, then sees SETTLED.
    job = Job.objects.select_for_update().get(pk=job.pk)

    method = validated_data.get('payment_method', 'CASH')
    split_legs = validated_data.get('split_legs', []) or []
    balance = check_balance_request(job.payment_state, job.balance_due, method, split_legs)

    result = {}
    change_given = validated_data.get('change_given')
    if validated_data.get('wallet_credit_amount'):
        result.update(_apply_wallet_credit(
            job=job, requested_amount=validated_data['wallet_credit_amount'],
            wallet_consent=validated_data.get('wallet_consent'), actor=actor,
        ))
        overflow = result.pop('_overflow', Decimal('0'))
        if overflow > 0 and change_given is not None:
            change_given = Decimal(str(change_given)) + overflow
    if method == 'WALLET':
        result.update(_redeem_wallet_credit(job=job, actor=actor, amount=balance))

    job.amount_paid = (job.amount_paid or Decimal('0')) + balance
    job.momo_reference = validated_data.get('momo_reference', '') or job.momo_reference
    job.pos_approval_code = validated_data.get('pos_approval_code', '') or job.pos_approval_code
    job.cash_tendered = validated_data.get('cash_tendered')
    job.change_given = change_given
    job.save(update_fields=['amount_paid', 'momo_reference', 'pos_approval_code',
                            'cash_tendered', 'change_given', 'updated_at'])

    _apply_payment_axes(job, actor)          # paid >= cost: SETTLED, logged
    job.refresh_from_db(fields=['payment_state'])
    if job.payment_state != 'SETTLED':       # never report a balance taken that did not settle
        raise ValueError('The balance did not settle the job. Nothing was taken; ask the BM to check its price.')

    result.update({
        'job_number': job.job_number,
        'is_balance': True,
        'amount_paid': str(balance),
        'balance_due': '0.00',
        'payment_method': method,
        'cash_tendered': str(validated_data['cash_tendered']) if validated_data.get('cash_tendered') is not None else None,
        'change_given': str(change_given) if change_given is not None else None,
    })
    _issue_receipt(job, validated_data, actor, method, split_legs, balance, result)

    broadcast_invalidation(job.branch.id, [
        'paymentQueue', 'cashierSummary', 'shiftStatus', 'todaySummary', 'jobStats',
        'jobs', 'cashierBalances', 'workload', 'workload-list',
    ])
    return result
