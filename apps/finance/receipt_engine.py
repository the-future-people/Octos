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
        from apps.finance import payment_methods as pm

        entry      = pm.get(payment_method)
        references = {
            'momo_reference'   : momo_reference,
            'pos_approval_code': pos_approval_code,
        }
        if entry and entry.requires and not references.get(entry.requires):
            raise ValueError(
                f'A reference is mandatory for {entry.label} payments.'
            )

        # ── Customer snapshot ─────────────────────────────────────────
        customer_name, phone = self._snapshot_customer(job, customer_phone)

        # A business's or institution's job: the receipt is the
        # organisation's alone, with its name and number. Never the person
        # who ordered it, nor the rep the record was opened with.
        org = getattr(job, 'customer', None)
        if org is not None and org.customer_type in ('BUSINESS', 'INSTITUTION'):
            customer_name = org.company_name or customer_name
            phone = org.phone or phone
            company_name = ''   # the name above is the company: not twice

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

    def send_whatsapp(self, receipt):
        """
        The receipt on WhatsApp. Returns (sent, reason).

        WhatsApp lets a business send a free message only to someone who
        wrote to it in the last 24 hours. So this works when the customer
        has been chatting with us, and says so plainly when not: the
        receipt stays as it was, and staff can print it.

        SENT here means handed to WhatsApp. Whether it arrived shows on
        the customer's conversation (delivered, read). A receipt never
        falls back to SMS: see NO_SMS_FALLBACK in whatsapp_outbound.
        """
        from apps.communications.services.whatsapp_outbound import try_send_text
        from apps.finance.models import Receipt

        if not receipt.customer_phone:
            return False, 'This receipt has no phone number to send it to.'

        # Formatting first, on its own: a receipt that can't be written out
        # (one with no job, say) must not be reported as WhatsApp being down.
        try:
            text = self._format_whatsapp_message(receipt)
        except Exception:
            logger.exception(
                'ReceiptEngine: receipt %s could not be formatted for WhatsApp',
                receipt.receipt_number,
            )
            return False, "This receipt couldn't be prepared for WhatsApp. Print it instead."

        # The receipt as a picture, in Farhat's colours (13 Nov 2026), with a
        # one-line caption. If it can't be drawn, the text receipt goes
        # instead: a customer never gets nothing.
        image, caption = None, text
        try:
            from apps.finance.services.receipt_image import receipt_data, render
            data = receipt_data(receipt)
            image = render(data)
            name = data.get('first_name')
            job_part = f" for {data['job_number']}" if data.get('job_number') else ' from Farhat Printing Press'
            caption = f"Your receipt{job_part}. Thank you{', ' + name if name else ''} 🙏"
        except Exception:
            logger.exception(
                'ReceiptEngine: receipt %s picture could not be drawn; sending the text receipt',
                receipt.receipt_number,
            )
            image, caption = None, text

        try:
            message = try_send_text(
                receipt.customer_phone, caption, kind='receipt',
                image=image, filename=f'{receipt.receipt_number}.png',
            )
        except Exception:
            logger.exception(
                'ReceiptEngine: WhatsApp receipt %s could not be queued',
                receipt.receipt_number,
            )
            return False, "WhatsApp couldn't be reached just now. Try again, or print the receipt."

        if message is None:
            return False, (
                "This customer hasn't written to us on WhatsApp in the last 24 hours, "
                "so WhatsApp won't let us send it. Print the receipt, or ask them to "
                "send us a message first, then try again."
            )

        receipt.whatsapp_status = Receipt.DeliveryStatus.SENT
        receipt.whatsapp_sent_at = timezone.now()
        receipt.save(update_fields=['whatsapp_status', 'whatsapp_sent_at'])
        return True, ''
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
            row(
                'Cashier:',
                receipt.cashier.full_name if receipt.cashier else 'Paid online',
            ),
            SEP,
        ]

        # ── Customer ──────────────────────────────────────────────────
        lines.append(row('Customer:', receipt.customer_name or 'Walk-in'))
        # A business account already reads as the business on the customer
        # line, so printing the same name twice adds nothing.
        if receipt.company_name and receipt.company_name != receipt.customer_name:
            lines.append(row('Company:', receipt.company_name))
        from apps.core.phones import display as _display_phone
        org = receipt.job.customer if receipt.job_id else None
        if org is not None and org.customer_type in ('BUSINESS', 'INSTITUTION') and org.address:
            lines.append(row('Address:', org.address[:32]))
        lines.append(row('Phone:', _display_phone(receipt.customer_phone) if receipt.customer_phone else '—'))
        lines.append(SEP)

        # ── Job details ───────────────────────────────────────────────
        lines += [
            row('Job No:', job.job_number),
            row('Type:', job.job_type or '—'),
            SEP,
        ]

        # ── Line items — tabulated downward ───────────────────────────
        # Items, numbered and described one way everywhere (13 Nov 2026):
        # jobs/services/item_lines.py, shared with the payment modal.
        from apps.jobs.services.item_lines import thermal as thermal_items
        item_rows = thermal_items(job.line_items.select_related('service').order_by('position'), W)
        if item_rows:
            lines.extend(item_rows)
        else:
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

        # ── Floor work: when it will be ready, and where to follow it ──
        # Only production and design that have joined the line. The PIN
        # is never printed: paper is left on counters; it goes to the
        # customer's phone when the job is ready.
        if job.job_type in ('PRODUCTION', 'DESIGN') and job.estimated_ready_at:
            from django.utils import timezone
            from apps.storefront.models import OnlineOrder
            from apps.storefront.services.messages import STOREFRONT
            at = timezone.localtime(job.estimated_ready_at)
            day = 'TODAY' if at.date() == timezone.localdate() else at.strftime('%a %d %b').upper()
            lines.append(SEP)
            lines.append(row('READY ABOUT', f"{at.strftime('%I:%M %p').lstrip('0')} {day}"))
            if job.balance_due:
                lines.append(row('BALANCE ON COLLECTION', f"GHS {float(job.balance_due):,.2f}"))
            order = OnlineOrder.objects.filter(job=job).only('short_code').first()
            if order and order.short_code:
                link = f"{STOREFRONT}/t/{order.short_code}".replace('https://', '')
                lines.append('Follow it:')
                lines.append(f"  {link[:W - 2]}")
            lines += [
                'Your collection PIN will be sent to',
                'your phone when it is ready.',
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
        # The same numbered items as the printed receipt (13 Nov 2026).
        from apps.jobs.services.item_lines import whatsapp as whatsapp_items
        item_rows = whatsapp_items(job.line_items.select_related('service').order_by('position'))
        if item_rows:
            lines.append("*Services:*")
            lines.extend(item_rows)
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

        if receipt.company_name and receipt.company_name != receipt.customer_name:
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

        Business accounts are named by the business, never the individual
        who happened to come in. A representative may leave the company or
        be replaced, and the receipt records who owes the money — which is
        the business. display_name already resolves this: company_name for
        a business, the person's name otherwise.
        """
        if job.customer:
            return (
                job.customer.display_name or 'Customer',
                getattr(job.customer, 'phone', '') or walk_in_phone,
            )
        # No record, but the job is linked to a WhatsApp chat (11 Nov 2026):
        # the chat names them, so the receipt can always be matched to the
        # person and their chat, never just "Walk-in Customer".
        from apps.communications.services.chat_customer import chat_identity
        who = chat_identity(job)
        if who is not None:
            return who[0], who[1] or walk_in_phone
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