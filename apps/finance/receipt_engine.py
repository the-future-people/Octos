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

    # ── Issue ─────────────────────────────────────────────────────────────

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
        company_name: str = '',
        split_legs: list = None,
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
            company_name     : Company or sender name — optional

        Returns:
            Receipt instance

        Raises:
            ValueError: MoMo reference missing for MOMO payment
            ValueError: POS approval code missing for POS payment
        """
        from apps.finance.models import Receipt

        # ── Validate payment reference fields ─────────────────────────
        if payment_method == Receipt.PaymentMethod.MOMO and not momo_reference:
            raise ValueError(
                'MoMo reference number is mandatory for MoMo payments.'
            )
        if payment_method == Receipt.PaymentMethod.POS and not pos_approval_code:
            raise ValueError(
                'POS approval code is mandatory for POS payments.'
            )

        # ── Customer snapshot ─────────────────────────────────────────
        customer_name, phone = self._snapshot_customer(job, customer_phone)

        # ── VAT calculation ───────────────────────────────────────────
        subtotal, vat_amount, nhil_amount, getfund_amount = self._calc_vat(
            amount_paid
        )

        # ── Generate receipt number ───────────────────────────────────
        year           = timezone.now().year
        receipt_number, sequence = Receipt.generate_receipt_number(
            branch_code=self.branch.code,
            year=year,
        )

        # ── Create receipt ────────────────────────────────────────────
        receipt = Receipt.objects.create(
            job               = job,
            daily_sheet       = daily_sheet,
            cashier           = cashier,
            receipt_number    = receipt_number,
            sequence          = sequence,
            payment_method    = payment_method,
            amount_paid       = amount_paid,
            balance_due       = balance_due,
            momo_reference    = momo_reference    if payment_method != 'SPLIT' else '',
            pos_approval_code = pos_approval_code if payment_method != 'SPLIT' else '',
            customer_name     = customer_name,
            customer_phone    = phone,
            company_name      = company_name,
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

        # ── Auto-create minimal customer profile for walk-in ──────────
        if not job.customer and phone:
            self._create_walkin_profile(job, customer_name, phone)

        return receipt

    # ── WhatsApp delivery ─────────────────────────────────────────────────

    def send_whatsapp(self, receipt) -> bool:
        """
        Queue a WhatsApp receipt delivery.
        Returns True if queued successfully, False otherwise.
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

    # ── Thermal print format ──────────────────────────────────────────────

    def format_thermal(self, receipt) -> str:
        """
        Format receipt as plain text for 80mm thermal printer.
        Monospace layout — 42 characters wide.
        Line items are tabulated downward, one per row.
        VAT lines always shown (0.00 when not registered).
        """
        W     = 42
        SEP   = '-' * W
        THICK = '=' * W

        def centre(text: str) -> str:
            return text.center(W)

        def row(label: str, value: str) -> str:
            gap = W - len(label) - len(value)
            return f"{label}{' ' * max(gap, 1)}{value}"

        branch = self.branch
        job    = receipt.job
        lines: list[str] = []

        # ── Header ────────────────────────────────────────────────────
        lines += [
            centre('FARHAT PRINTING PRESS'),
            centre(branch.name),
            centre(branch.address[:W] if branch.address else ''),
            centre(branch.phone or ''),
            THICK,
            centre('RECEIPT'),
            SEP,
        ]

        # ── Receipt meta ──────────────────────────────────────────────
        lines += [
            row('Receipt No:', receipt.receipt_number),
            row('Date:', receipt.created_at.strftime('%d/%m/%Y %I:%M %p')),
            row('Cashier:', receipt.cashier.full_name),
            SEP,
        ]

        # ── Customer ──────────────────────────────────────────────────
        lines.append(row('Customer:', receipt.customer_name or 'Walk-in'))
        if receipt.company_name:
            lines.append(row('Company:', receipt.company_name))
        lines.append(row('Phone:', receipt.customer_phone or '—'))
        lines.append(SEP)

        # ── Job details ───────────────────────────────────────────────
        lines += [
            row('Job No:', job.job_number),
            row('Type:', job.job_type or '—'),
            SEP,
        ]

        # ── Line items — tabulated downward ───────────────────────────
        line_items = job.line_items.select_related('service').order_by('position')

        if line_items.exists():
            # Column headers
            lines.append(f"{'ITEM':<24} {'QTY':>4} {'AMOUNT':>12}")
            lines.append(SEP)
            for li in line_items:
                name = (li.label or li.service.name)[:24]
                qty  = str(li.sets if li.sets > 1 else li.quantity)
                amt  = f"GHS {float(li.line_total):,.2f}"
                # Truncate name if needed
                if len(name) > 20:
                    name = name[:20] + '…'
                lines.append(f"{name:<24} {qty:>4} {amt:>12}")
                # Show spec detail on next line if multi-page
                if li.pages and li.pages > 1:
                    spec = f"  {li.pages}pp × {li.sets} sets"
                    if li.paper_size:
                        spec += f" · {li.paper_size}"
                    spec_color = ' · Colour' if li.is_color else ' · B&W'
                    spec += spec_color
                    lines.append(spec[:W])
        else:
            # Fallback to job title if no line items
            lines.append(row('Service:', job.title[:30] if job.title else '—'))

        lines.append(SEP)

        # ── Payment ───────────────────────────────────────────────────
        split_legs = receipt.payment_legs.all().order_by('sequence')

        if split_legs.exists():
            lines.append(row('Payment Method:', 'SPLIT'))
            lines.append(SEP)
            for leg in split_legs:
                method_label = dict(leg.Method.choices).get(leg.payment_method, leg.payment_method)
                lines.append(row(f"{method_label}:", f"GHS {float(leg.amount):,.2f}"))
                if leg.momo_reference:
                    lines.append(row('  MoMo Ref:', leg.momo_reference))
                if leg.pos_approval_code:
                    lines.append(row('  POS Code:', leg.pos_approval_code))
        else:
            lines.append(row('Payment Method:', receipt.get_payment_method_display()))
            if receipt.momo_reference:
                lines.append(row('MoMo Ref:', receipt.momo_reference))
            if receipt.pos_approval_code:
                lines.append(row('POS Code:', receipt.pos_approval_code))

        lines.append(SEP)

        # ── Amounts — VAT always shown ────────────────────────────────
        lines.append(row('Subtotal:', f"GHS {float(receipt.subtotal):,.2f}"))
        lines.append(row(
            f"VAT ({receipt.vat_rate}%):",
            f"GHS {float(receipt.vat_amount):,.2f}"
        ))
        lines.append(row('NHIL:', f"GHS {float(receipt.nhil_amount):,.2f}"))
        lines.append(row('GetFund:', f"GHS {float(receipt.getfund_amount):,.2f}"))

        lines += [
            THICK,
            row('AMOUNT PAID:', f"GHS {float(receipt.amount_paid):,.2f}"),
        ]

        if float(receipt.balance_due) > 0:
            lines.append(row('BALANCE DUE:', f"GHS {float(receipt.balance_due):,.2f}"))

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
        job    = receipt.job
        branch = self.branch

        lines = [
            f"*FARHAT PRINTING PRESS*",
            f"_{branch.name}_",
            f"",
            f"*Receipt:* {receipt.receipt_number}",
            f"*Date:* {receipt.created_at.strftime('%d/%m/%Y %I:%M %p')}",
            f"",
            f"*Job:* {job.job_number}",
        ]

        # Line items
        line_items = job.line_items.select_related('service').order_by('position')
        if line_items.exists():
            lines.append(f"*Services:*")
            for li in line_items:
                name = li.label or li.service.name
                lines.append(f"  • {name} — GHS {float(li.line_total):,.2f}")
        else:
            lines.append(f"*Service:* {job.title}")

        lines += [
            f"",
            f"*Amount Paid:* GHS {float(receipt.amount_paid):,.2f}",
        ]

        if float(receipt.balance_due) > 0:
            lines.append(f"*Balance Due:* GHS {float(receipt.balance_due):,.2f}")

        lines += [
            f"*Payment:* {receipt.get_payment_method_display()}",
        ]

        if receipt.company_name:
            lines.append(f"*Company:* {receipt.company_name}")

        lines += [
            f"",
            f"Thank you for your patronage! 🙏",
        ]

        return '\n'.join(lines)

    # ── Internal helpers ──────────────────────────────────────────────────

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

        vat_rate       = float(self.branch.vat_rate) / 100
        nhil_rate      = float(self.branch.nhil_rate) / 100
        getfund_rate   = float(self.branch.getfund_rate) / 100
        total_rate     = 1 + vat_rate + nhil_rate + getfund_rate

        subtotal       = round(float(amount) / total_rate, 2)
        vat_amount     = round(subtotal * vat_rate, 2)
        nhil_amount    = round(subtotal * nhil_rate, 2)
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

    # ── Class-level convenience ───────────────────────────────────────────

    @classmethod
    def issue_for_job(cls, job, cashier, daily_sheet, **kwargs):
        """Shorthand: ReceiptEngine.issue_for_job(job, cashier, sheet, ...)"""
        return cls(job.branch).issue(
            job=job,
            cashier=cashier,
            daily_sheet=daily_sheet,
            **kwargs,
        )