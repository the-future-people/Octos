from __future__ import annotations

import logging
from typing import Optional

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class ReceiptEngine:
    """
    Generates and delivers receipts for all payment confirmations.

    Responsibilities:
    - Generate sequential receipt numbers per branch per year
    - Snapshot customer and payment details at time of issue
    - Apply VAT fields (zero until branch is GRA registered)
    - Queue WhatsApp delivery
    - Format for thermal printer (80mm)

    Rules:
    - Receipts are immutable once issued — no edits ever
    - MoMo payments require a reference number
    - POS payments require an approval code
    - Walk-in customers with no profile get a minimal snapshot
    - Receipt number sequence is atomic — no gaps, no duplicates
    """

    def __init__(self, branch) -> None:
        self.branch = branch

    # ── Issue ─────────────────────────────────────────────────────

    @transaction.atomic
    def issue(
        self,
        job,
        cashier,
        daily_sheet,
        payment_method: str,
        amount_paid,
        balance_due=0,
        momo_reference: str = '',
        pos_approval_code: str = '',
        customer_phone: str = '',
    ):
        """
        Issue a receipt for a completed payment.

        Args:
            job              : Job instance payment is for
            cashier          : CustomUser confirming the payment
            daily_sheet      : DailySalesSheet the job belongs to
            payment_method   : CASH | MOMO | POS | CREDIT
            amount_paid      : Decimal amount collected
            balance_due      : Decimal balance still owed (0 if full payment)
            momo_reference   : Mandatory for MOMO payments
            pos_approval_code: Mandatory for POS payments
            customer_phone   : For walk-in customers with no profile

        Returns:
            Receipt instance

        Raises:
            ValueError: MoMo reference missing for MOMO payment
            ValueError: POS approval code missing for POS payment
        """
        from apps.finance.models import Receipt

        # ── Validate payment reference fields ─────────────────────
        if payment_method == Receipt.PaymentMethod.MOMO and not momo_reference:
            raise ValueError(
                'MoMo reference number is mandatory for MoMo payments.'
            )
        if payment_method == Receipt.PaymentMethod.POS and not pos_approval_code:
            raise ValueError(
                'POS approval code is mandatory for POS payments.'
            )

        # ── Customer snapshot ──────────────────────────────────────
        customer_name, phone = self._snapshot_customer(
            job, customer_phone
        )

        # ── VAT calculation ────────────────────────────────────────
        subtotal, vat_amount, nhil_amount, getfund_amount = self._calc_vat(
            amount_paid
        )

        # ── Generate receipt number ────────────────────────────────
        year           = timezone.now().year
        receipt_number, sequence = Receipt.generate_receipt_number(
            branch_code=self.branch.code,
            year=year,
        )

        # ── Create receipt ─────────────────────────────────────────
        receipt = Receipt.objects.create(
            job               = job,
            daily_sheet       = daily_sheet,
            cashier           = cashier,
            receipt_number    = receipt_number,
            sequence          = sequence,
            payment_method    = payment_method,
            amount_paid       = amount_paid,
            balance_due       = balance_due,
            momo_reference    = momo_reference,
            pos_approval_code = pos_approval_code,
            customer_name     = customer_name,
            customer_phone    = phone,
            subtotal          = subtotal,
            vat_rate          = self.branch.vat_rate,
            vat_amount        = vat_amount,
            nhil_amount       = nhil_amount,
            getfund_amount    = getfund_amount,
        )

        logger.info(
            'ReceiptEngine: issued %s for job %s — GHS %s',
            receipt_number,
            job.job_number,
            amount_paid,
        )

        # ── Auto-create minimal customer profile for walk-in ───────
        if not job.customer and phone:
            self._create_walkin_profile(job, customer_name, phone)

        return receipt

    # ── WhatsApp delivery ─────────────────────────────────────────

    def send_whatsapp(self, receipt) -> bool:
        """
        Queue a WhatsApp receipt delivery.
        Returns True if queued successfully, False otherwise.

        Currently logs the intent — wire to WhatsApp API when ready.
        """
        from apps.finance.models import Receipt

        phone = receipt.customer_phone
        if not phone:
            logger.warning(
                'ReceiptEngine: no phone number for receipt %s — '
                'WhatsApp delivery skipped',
                receipt.receipt_number,
            )
            return False

        try:
            message = self._format_whatsapp_message(receipt)

            # TODO: wire to WhatsApp Business API / Twilio
            # For now, log the intent and mark as sent
            logger.info(
                'ReceiptEngine: WhatsApp receipt queued for %s → %s',
                receipt.receipt_number,
                phone,
            )

            receipt.whatsapp_status  = Receipt.DeliveryStatus.SENT
            receipt.whatsapp_sent_at = timezone.now()
            receipt.save(update_fields=['whatsapp_status', 'whatsapp_sent_at'])
            return True

        except Exception as exc:
            logger.exception(
                'ReceiptEngine: WhatsApp delivery failed for %s: %s',
                receipt.receipt_number,
                exc,
            )
            receipt.whatsapp_status = Receipt.DeliveryStatus.FAILED
            receipt.save(update_fields=['whatsapp_status'])
            return False

    # ── Thermal print format ──────────────────────────────────────

    def format_thermal(self, receipt) -> str:
        """
        Format receipt as plain text for 80mm thermal printer.
        Monospace layout — 42 characters wide.

        Returns a string ready to send to the printer.
        """
        W     = 42
        SEP   = '-' * W
        THICK = '=' * W

        def centre(text: str) -> str:
            return text.center(W)

        def row(label: str, value: str) -> str:
            gap = W - len(label) - len(value)
            return f"{label}{' ' * max(gap, 1)}{value}"

        branch    = self.branch
        job       = receipt.job
        lines: list[str] = []

        # Header
        lines += [
            centre('FARHAT PRINTING PRESS'),
            centre(branch.name),
            centre(branch.address[:W] if branch.address else ''),
            centre(branch.phone or ''),
            THICK,
            centre('RECEIPT'),
            SEP,
        ]

        # Receipt meta
        lines += [
            row('Receipt No:', receipt.receipt_number),
            row('Date:', receipt.created_at.strftime('%d/%m/%Y %I:%M %p')),
            row('Cashier:', receipt.cashier.full_name),
            SEP,
        ]

        # Customer
        lines += [
            row('Customer:', receipt.customer_name or 'Walk-in'),
            row('Phone:', receipt.customer_phone or '—'),
            SEP,
        ]

        # Job details
        lines += [
            row('Job No:', job.job_number),
            row('Service:', job.title),
            row('Type:', job.job_type),
            SEP,
        ]

        # Payment
        lines += [
            row('Payment Method:', receipt.get_payment_method_display()),
        ]

        if receipt.momo_reference:
            lines.append(row('MoMo Ref:', receipt.momo_reference))
        if receipt.pos_approval_code:
            lines.append(row('POS Code:', receipt.pos_approval_code))

        lines.append(SEP)

        # Amounts
        lines += [
            row('Subtotal:', f"GHS {receipt.subtotal:.2f}"),
        ]

        if float(receipt.vat_rate) > 0:
            lines += [
                row(f"VAT ({receipt.vat_rate}%):", f"GHS {receipt.vat_amount:.2f}"),
                row('NHIL:', f"GHS {receipt.nhil_amount:.2f}"),
                row('GetFund:', f"GHS {receipt.getfund_amount:.2f}"),
            ]

        lines += [
            THICK,
            row('AMOUNT PAID:', f"GHS {receipt.amount_paid:.2f}"),
        ]

        if float(receipt.balance_due) > 0:
            lines += [
                row('BALANCE DUE:', f"GHS {receipt.balance_due:.2f}"),
            ]

        lines += [
            THICK,
            centre('Thank you for choosing Farhat!'),
            centre('Keep this receipt for your records.'),
            '',
        ]

        return '\n'.join(lines)

    def _format_whatsapp_message(self, receipt) -> str:
        """
        Format receipt as a WhatsApp message.
        Concise, readable on a phone screen.
        """
        job      = receipt.job
        branch   = self.branch
        lines    = [
            f"*FARHAT PRINTING PRESS*",
            f"_{branch.name}_",
            f"",
            f"*Receipt:* {receipt.receipt_number}",
            f"*Date:* {receipt.created_at.strftime('%d/%m/%Y %I:%M %p')}",
            f"",
            f"*Job:* {job.job_number}",
            f"*Service:* {job.title}",
            f"",
            f"*Amount Paid:* GHS {receipt.amount_paid:.2f}",
        ]

        if float(receipt.balance_due) > 0:
            lines.append(f"*Balance Due:* GHS {receipt.balance_due:.2f}")

        lines += [
            f"*Payment:* {receipt.get_payment_method_display()}",
            f"",
            f"Thank you for your patronage! 🙏",
        ]

        return '\n'.join(lines)

    # ── Internal helpers ──────────────────────────────────────────

    def _snapshot_customer(self, job, walk_in_phone: str) -> tuple[str, str]:
        """
        Return (customer_name, phone) for the receipt snapshot.
        Falls back to walk-in details if no customer profile.
        """
        if job.customer:
            return (
                job.customer.full_name or 'Customer',
                getattr(job.customer, 'phone', '') or walk_in_phone,
            )
        return 'Walk-in Customer', walk_in_phone

    def _calc_vat(self, amount) -> tuple:
        """
        Calculate VAT breakdown.
        Returns (subtotal, vat_amount, nhil_amount, getfund_amount).
        All zero until branch is VAT registered.
        """
        if not self.branch.vat_registered:
            return amount, 0, 0, 0

        vat_rate      = float(self.branch.vat_rate) / 100
        nhil_rate     = float(self.branch.nhil_rate) / 100
        getfund_rate  = float(self.branch.getfund_rate) / 100
        total_rate    = 1 + vat_rate + nhil_rate + getfund_rate

        subtotal      = round(float(amount) / total_rate, 2)
        vat_amount    = round(subtotal * vat_rate, 2)
        nhil_amount   = round(subtotal * nhil_rate, 2)
        getfund_amount = round(subtotal * getfund_rate, 2)

        return subtotal, vat_amount, nhil_amount, getfund_amount

    def _create_walkin_profile(self, job, name: str, phone: str) -> None:
        """
        Auto-create a minimal CustomerProfile for a walk-in customer
        who provided a phone number for receipt delivery.
        Links the profile back to the job.
        """
        try:
            from apps.customers.models import CustomerProfile

            customer = CustomerProfile.objects.create(
                full_name = name or 'Walk-in Customer',
                phone     = phone,
                branch    = self.branch,
                is_walkin = True,
            )
            job.customer = customer
            job.save(update_fields=['customer', 'updated_at'])

            logger.info(
                'ReceiptEngine: created walk-in profile %s for job %s',
                customer.pk,
                job.job_number,
            )
        except Exception:
            logger.exception(
                'ReceiptEngine: failed to create walk-in profile for job %s',
                job.job_number,
            )

    # ── Class-level convenience ───────────────────────────────────

    @classmethod
    def issue_for_job(cls, job, cashier, daily_sheet, **kwargs):
        """Shorthand: ReceiptEngine.issue_for_job(job, cashier, sheet, ...)"""
        return cls(job.branch).issue(
            job=job,
            cashier=cashier,
            daily_sheet=daily_sheet,
            **kwargs,
        )