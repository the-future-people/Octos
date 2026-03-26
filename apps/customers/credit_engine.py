from decimal import Decimal
from django.db import transaction
from django.utils import timezone


class CreditLimitExceeded(Exception):
    """Raised when a job would push a credit account over its limit."""
    def __init__(self, available, required):
        self.available = available
        self.required  = required
        super().__init__(
            f"Credit limit exceeded. Available: GHS {available:.2f}, "
            f"Required: GHS {required:.2f}. "
            f"Customer must settle at least GHS {required - available:.2f} before proceeding."
        )


class CreditAccountNotActive(Exception):
    """Raised when a credit account is not in ACTIVE status."""
    pass


class CreditEngine:
    """
    Core engine for all credit account operations.

    Responsibilities:
    - Eligibility checks before issuing credit on a job
    - Deducting (increasing balance) when a credit job is confirmed
    - Settling (reducing balance) when a customer pays
    - Computing customer confidence scores
    - Determining system auto-recommendation eligibility
    """

    # ── Confidence score thresholds ───────────────────────────
    CONFIDENCE_RECOMMEND_THRESHOLD = 50   # system flags for BM attention
    CONFIDENCE_MAX                 = 100

    # ── Score weights ─────────────────────────────────────────
    WEIGHT_JOB_COUNT       = 0.4   # 40% — volume of business
    WEIGHT_PAYMENT_CONSIST = 0.3   # 30% — always paid on time
    WEIGHT_PROFILE_COMPLETE= 0.2   # 20% — company name, address on file
    WEIGHT_TENURE          = 0.1   # 10% — how long they've been a customer

    # ── Eligibility ───────────────────────────────────────────

    @staticmethod
    def check_eligibility(credit_account, amount: Decimal) -> None:
        """
        Raises CreditAccountNotActive or CreditLimitExceeded if the
        customer cannot take on 'amount' of new credit.
        Does nothing if the account is valid and has headroom.
        """
        from apps.finance.models import CreditAccount

        if credit_account.status != CreditAccount.Status.ACTIVE:
            raise CreditAccountNotActive(
                f"Credit account is {credit_account.status}. "
                f"Only ACTIVE accounts can be used for credit jobs."
            )

        available = credit_account.available_credit
        if Decimal(str(amount)) > available:
            raise CreditLimitExceeded(
                available=available,
                required=Decimal(str(amount)),
            )

    # ── Deduct (issue credit on a job) ────────────────────────

    @staticmethod
    @transaction.atomic
    def deduct(credit_account, job) -> None:
        """
        Increases the credit account balance by the job's amount_paid.
        Links the job to the credit account.
        Call this when a CREDIT job is confirmed by the cashier.
        """
        amount = job.amount_paid or job.estimated_cost or Decimal('0.00')

        # Final eligibility check inside the transaction
        CreditEngine.check_eligibility(credit_account, amount)

        credit_account.current_balance += Decimal(str(amount))
        credit_account.save(update_fields=['current_balance', 'updated_at'])

        # Link job to credit account
        job.credit_account = credit_account
        job.save(update_fields=['credit_account', 'updated_at'])

    # ── Settle (customer pays down their balance) ─────────────

    @staticmethod
    @transaction.atomic
    def settle(
        credit_account,
        amount: Decimal,
        method: str,
        sheet,
        cashier,
        reference: str = '',
        notes: str = '',
    ):
        """
        Records a credit settlement payment.
        Reduces the credit account balance.
        Creates a CreditPayment record and a Receipt.
        Returns the CreditPayment instance.
        """
        from apps.finance.models import CreditPayment

        amount = Decimal(str(amount))

        if amount <= 0:
            raise ValueError("Settlement amount must be greater than zero.")

        if credit_account.status not in (
            'ACTIVE', 'SUSPENDED'  # allow settlement even on suspended accounts
        ):
            raise CreditAccountNotActive(
                "Cannot settle a CLOSED or PENDING credit account."
            )

        balance_before = credit_account.current_balance
        balance_after  = max(balance_before - amount, Decimal('0.00'))

        # Create payment record
        payment = CreditPayment.objects.create(
            credit_account = credit_account,
            daily_sheet    = sheet,
            received_by    = cashier,
            amount         = amount,
            payment_method = method,
            momo_reference = reference if method == 'MOMO' else '',
            pos_approval_code = reference if method == 'POS' else '',
            balance_before = balance_before,
            balance_after  = balance_after,
            notes          = notes,
        )

        # Update balance
        credit_account.current_balance = balance_after
        # If account was suspended and now cleared, reactivate
        if credit_account.status == 'SUSPENDED' and balance_after == 0:
            credit_account.status = 'ACTIVE'
        credit_account.save(update_fields=['current_balance', 'status', 'updated_at'])

        # ── Update sheet totals ───────────────────────────────
        from django.db.models import F
        from apps.finance.models import DailySalesSheet

        method_field = {
            'CASH': 'total_cash',
            'MOMO': 'total_momo',
            'POS' : 'total_pos',
        }.get(method)

        sheet_update = {'total_credit_settled': F('total_credit_settled') + amount}
        if method_field:
            sheet_update[method_field] = F(method_field) + amount

        DailySalesSheet.objects.filter(pk=sheet.pk).update(**sheet_update)
        # ── Generate settlement receipt ───────────────────────
        from apps.finance.models import Receipt
        branch_code = sheet.branch.code
        year        = payment.created_at.year
        receipt_number, sequence = Receipt.generate_receipt_number(branch_code, year)

        Receipt.objects.create(
            job            = None,
            receipt_type   = Receipt.ReceiptType.CREDIT_SETTLEMENT,
            daily_sheet    = sheet,
            cashier        = cashier,
            payment_method = method,
            amount_paid    = amount,
            balance_due    = 0,
            receipt_number = receipt_number,
            sequence       = sequence,
            customer_name  = credit_account.customer.display_name,
            customer_phone = credit_account.customer.phone,
            company_name   = credit_account.organisation_name or '',
            momo_reference    = reference if method == 'MOMO' else '',
            pos_approval_code = reference if method == 'POS'  else '',
            subtotal       = amount,
        )

        return payment

    # ── Confidence score ──────────────────────────────────────

    @staticmethod
    def compute_confidence_score(customer) -> int:
        """
        Computes a 0–100 confidence score for a customer based on:
        - Job volume (how much business they've brought)
        - Payment consistency (did they always pay promptly)
        - Profile completeness (company name, address on file)
        - Tenure (how long they've been a customer)

        Updates customer.confidence_score and saves.
        Returns the new score.
        """
        from apps.jobs.models import Job
        from django.db.models import Count, Q

        jobs = Job.objects.filter(customer=customer)
        total_jobs = jobs.count()

        if total_jobs == 0:
            customer.confidence_score = 0
            customer.save(update_fields=['confidence_score', 'updated_at'])
            return 0

        # ── Job volume score (0–40) ───────────────────────────
        # 40 points at 50+ completed jobs
        completed = jobs.filter(status='COMPLETE').count()
        volume_score = min(completed / 50, 1.0) * 40

        # ── Payment consistency score (0–30) ──────────────────
        # Ratio of paid jobs to total non-cancelled jobs
        non_cancelled = jobs.exclude(status='CANCELLED').count()
        paid = jobs.filter(
            status='COMPLETE',
            amount_paid__isnull=False,
            amount_paid__gt=0,
        ).count()
        consistency_score = (paid / non_cancelled * 30) if non_cancelled else 0

        # ── Profile completeness score (0–20) ─────────────────
        completeness = 0
        if customer.first_name and customer.last_name: completeness += 5
        if customer.phone:                             completeness += 5
        if customer.company_name:                      completeness += 5
        if customer.address:                           completeness += 5
        completeness_score = completeness  # already 0–20

        # ── Tenure score (0–10) ───────────────────────────────
        # 10 points at 12+ months
        if customer.created_at:
            months = (timezone.now() - customer.created_at).days / 30
            tenure_score = min(months / 12, 1.0) * 10
        else:
            tenure_score = 0

        total = int(
            volume_score +
            consistency_score +
            completeness_score +
            tenure_score
        )
        total = min(total, CreditEngine.CONFIDENCE_MAX)

        customer.confidence_score = total
        customer.save(update_fields=['confidence_score', 'updated_at'])

        return total

    @staticmethod
    def should_recommend(customer) -> bool:
        """
        Returns True if the customer's confidence score meets or exceeds
        the recommendation threshold and they don't already have an
        active/pending credit account.
        """
        from apps.finance.models import CreditAccount

        if customer.confidence_score < CreditEngine.CONFIDENCE_RECOMMEND_THRESHOLD:
            return False

        already_has_account = CreditAccount.objects.filter(
            customer=customer,
            status__in=['PENDING', 'ACTIVE'],
        ).exists()

        return not already_has_account