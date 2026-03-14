from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class CreditEngine:
    """
    Controls all credit account operations for Octos.

    Responsibilities:
    - Enforce credit limits before a job is completed on credit
    - Issue credit against a job (increases balance)
    - Process credit settlements (reduces balance)
    - Auto-suspend accounts that breach payment terms
    - Handle Belt Manager override requests
    - Notify relevant parties at each step

    Rules:
    - BM recommends, Belt Manager approves — no self-approval
    - System blocks credit job completion if account is over limit
    - BM can request override — Belt Manager must approve
    - Account auto-suspends if balance is unpaid past payment_terms days
    - No credit on credit — settlements must be Cash, MoMo or POS
    - Every balance change is logged with actor and timestamp
    """

    def __init__(self, credit_account) -> None:
        self.account = credit_account

    # ── Limit check ───────────────────────────────────────────────

    def can_issue_credit(self, amount) -> bool:
        """
        Check if the account can absorb a new credit of this amount.
        Returns False if account is inactive or would exceed limit.
        """
        if not self.account.is_active:
            return False
        if self.account.status != 'ACTIVE':
            return False
        projected = float(self.account.current_balance) + float(amount)
        return projected <= float(self.account.credit_limit)

    def check_or_raise(self, amount) -> None:
        """
        Raise ValueError if credit cannot be issued.
        Call this before completing a credit job.
        """
        if not self.account.is_active:
            raise ValueError(
                f"Credit account for {self.account.customer.full_name} "
                f"is {self.account.status} — credit cannot be issued."
            )
        if self.account.is_over_limit:
            raise ValueError(
                f"Credit account for {self.account.customer.full_name} "
                f"is at its limit (GHS {self.account.credit_limit}). "
                f"Balance must be settled before further credit."
            )
        projected = float(self.account.current_balance) + float(amount)
        if projected > float(self.account.credit_limit):
            available = self.account.available_credit
            raise ValueError(
                f"This job (GHS {amount}) would exceed the credit limit. "
                f"Available credit: GHS {available:.2f}."
            )

    # ── Issue credit ──────────────────────────────────────────────

    @transaction.atomic
    def issue_credit(
        self,
        job,
        amount,
        actor,
        daily_sheet,
    ):
        """
        Issue credit against a job.
        Increases the account's current_balance by amount.

        Args:
            job         : Job instance being completed on credit
            amount      : Decimal amount of credit being issued
            actor       : CustomUser completing the job
            daily_sheet : DailySalesSheet for today

        Returns:
            CreditAccount with updated balance

        Raises:
            ValueError : Account inactive, over limit, or would exceed limit
        """
        self.check_or_raise(amount)

        balance_before = Decimal(str(self.account.current_balance))
        balance_after  = balance_before + Decimal(str(amount))

        self.account.current_balance = balance_after
        self.account.save(update_fields=['current_balance', 'updated_at'])

        logger.info(
            'CreditEngine: issued GHS %s credit to %s — balance %s → %s',
            amount,
            self.account.customer.full_name,
            balance_before,
            balance_after,
        )

        self._notify_credit_issued(job, amount, balance_after)
        return self.account

    # ── Settle credit ─────────────────────────────────────────────

    @transaction.atomic
    def settle(
        self,
        amount,
        payment_method: str,
        actor,
        daily_sheet,
        momo_reference: str = '',
        pos_approval_code: str = '',
        notes: str = '',
    ):
        """
        Process a credit settlement payment.
        Reduces the account's current_balance by amount.

        Args:
            amount            : Decimal amount being settled
            payment_method    : CASH | MOMO | POS
            actor             : CustomUser receiving the payment
            daily_sheet       : DailySalesSheet for today
            momo_reference    : Mandatory for MOMO
            pos_approval_code : Mandatory for POS
            notes             : Optional context

        Returns:
            CreditPayment instance

        Raises:
            ValueError : Invalid payment method, missing reference,
                         or amount exceeds current balance
        """
        from apps.finance.models import CreditPayment

        # Validate payment method
        valid_methods = {
            CreditPayment.PaymentMethod.CASH,
            CreditPayment.PaymentMethod.MOMO,
            CreditPayment.PaymentMethod.POS,
        }
        if payment_method not in valid_methods:
            raise ValueError(
                f"Invalid payment method '{payment_method}'. "
                f"Credit settlements accept Cash, MoMo or POS only."
            )

        # Validate references
        if payment_method == CreditPayment.PaymentMethod.MOMO and not momo_reference:
            raise ValueError(
                'MoMo reference number is mandatory for MoMo settlements.'
            )
        if payment_method == CreditPayment.PaymentMethod.POS and not pos_approval_code:
            raise ValueError(
                'POS approval code is mandatory for POS settlements.'
            )

        # Validate amount
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError('Settlement amount must be greater than zero.')
        if amount > self.account.current_balance:
            raise ValueError(
                f"Settlement amount (GHS {amount}) exceeds "
                f"outstanding balance (GHS {self.account.current_balance})."
            )

        balance_before = Decimal(str(self.account.current_balance))
        balance_after  = balance_before - amount

        # Update account balance
        self.account.current_balance = balance_after
        self.account.save(update_fields=['current_balance', 'updated_at'])

        # Record the payment
        payment = CreditPayment.objects.create(
            credit_account    = self.account,
            daily_sheet       = daily_sheet,
            received_by       = actor,
            amount            = amount,
            payment_method    = payment_method,
            momo_reference    = momo_reference,
            pos_approval_code = pos_approval_code,
            balance_before    = balance_before,
            balance_after     = balance_after,
            notes             = notes,
        )

        logger.info(
            'CreditEngine: settled GHS %s for %s — balance %s → %s',
            amount,
            self.account.customer.full_name,
            balance_before,
            balance_after,
        )

        # Reactivate if account was suspended and balance is now clear
        if (
            self.account.status == 'SUSPENDED'
            and balance_after == 0
        ):
            self.account.status = 'ACTIVE'
            self.account.suspended_at     = None
            self.account.suspension_reason = ''
            self.account.save(update_fields=[
                'status', 'suspended_at',
                'suspension_reason', 'updated_at',
            ])
            logger.info(
                'CreditEngine: account %s reactivated after full settlement',
                self.account.pk,
            )

        self._notify_settlement(payment)
        return payment

    # ── Auto-suspend overdue accounts ─────────────────────────────

    @classmethod
    def suspend_overdue_accounts(cls) -> int:
        """
        Suspend all active credit accounts where the balance
        has been outstanding longer than their payment_terms days.

        Returns count of accounts suspended.
        Called by a scheduled task.
        """
        from apps.finance.models import CreditAccount
        from apps.finance.models import CreditPayment

        now      = timezone.now()
        suspended = 0

        active_accounts = CreditAccount.objects.filter(
            status='ACTIVE',
            current_balance__gt=0,
        )

        for account in active_accounts:
            last_payment = (
                CreditPayment.objects
                .filter(credit_account=account)
                .order_by('-created_at')
                .first()
            )

            # Use last payment date or account approval date as reference
            reference_date = (
                last_payment.created_at
                if last_payment
                else account.approved_at or account.created_at
            )

            days_outstanding = (now - reference_date).days

            if days_outstanding > account.payment_terms:
                account.status           = 'SUSPENDED'
                account.suspended_at     = now
                account.suspension_reason = (
                    f"Auto-suspended: balance of GHS {account.current_balance} "
                    f"outstanding for {days_outstanding} days "
                    f"(terms: {account.payment_terms} days)."
                )
                account.save(update_fields=[
                    'status', 'suspended_at',
                    'suspension_reason', 'updated_at',
                ])
                suspended += 1
                cls._notify_suspension(account)
                logger.info(
                    'CreditEngine: auto-suspended account %s — %d days overdue',
                    account.pk,
                    days_outstanding,
                )

        return suspended

    # ── Notifications ─────────────────────────────────────────────

    def _notify_credit_issued(self, job, amount, new_balance) -> None:
        """Notify BM that credit was issued against a job."""
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            bm = CustomUser.objects.filter(
                branch=job.branch,
                role__name='BRANCH_MANAGER',
                is_active=True,
            ).first()

            if bm:
                notify(
                    recipient=bm,
                    verb='CREDIT_ISSUED',
                    message=(
                        f"Credit of GHS {amount} issued to "
                        f"{self.account.customer.full_name} "
                        f"for job {job.job_number}. "
                        f"New balance: GHS {new_balance}."
                    ),
                    link='/portal/finance/credit/',
                )
        except Exception:
            logger.exception(
                'CreditEngine: failed to notify BM on credit issue'
            )

    def _notify_settlement(self, payment) -> None:
        """Notify BM that a credit settlement was received."""
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            bm = CustomUser.objects.filter(
                branch=self.account.customer.branch,
                role__name='BRANCH_MANAGER',
                is_active=True,
            ).first()

            if bm:
                notify(
                    recipient=bm,
                    verb='CREDIT_SETTLED',
                    message=(
                        f"GHS {payment.amount} received from "
                        f"{self.account.customer.full_name}. "
                        f"Remaining balance: GHS {payment.balance_after}."
                    ),
                    link='/portal/finance/credit/',
                )
        except Exception:
            logger.exception(
                'CreditEngine: failed to notify BM on settlement'
            )

    @staticmethod
    def _notify_suspension(account) -> None:
        """Notify BM and Belt Manager of auto-suspension."""
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            # Notify branch manager
            bm = CustomUser.objects.filter(
                branch=account.customer.branch,
                role__name='BRANCH_MANAGER',
                is_active=True,
            ).first()

            if bm:
                notify(
                    recipient=bm,
                    verb='CREDIT_SUSPENDED',
                    message=(
                        f"Credit account for {account.customer.full_name} "
                        f"has been auto-suspended. "
                        f"Outstanding: GHS {account.current_balance}."
                    ),
                    link='/portal/finance/credit/',
                )

            # Notify belt manager
            belt_managers = CustomUser.objects.filter(
                role__name='BELT_MANAGER',
                is_active=True,
            )
            for belt_manager in belt_managers:
                notify(
                    recipient=belt_manager,
                    verb='CREDIT_SUSPENDED',
                    message=(
                        f"Credit account for {account.customer.full_name} "
                        f"auto-suspended at {account.customer.branch.name if account.customer.branch else 'unknown branch'}. "
                        f"Outstanding: GHS {account.current_balance}."
                    ),
                    link='/portal/finance/credit/',
                )
        except Exception:
            logger.exception(
                'CreditEngine: failed to notify on suspension for account %s',
                account.pk,
            )

    # ── Class-level convenience ───────────────────────────────────

    @classmethod
    def for_customer(cls, customer):
        """
        Shorthand: CreditEngine.for_customer(customer)
        Raises ValueError if customer has no credit account.
        """
        try:
            return cls(customer.credit_account)
        except Exception:
            raise ValueError(
                f"{customer.full_name} does not have a credit account."
            )