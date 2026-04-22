# apps/finance/services/invoice_service.py

import logging
from django.db import transaction

logger = logging.getLogger(__name__)


class InvoiceService:

    @staticmethod
    @transaction.atomic
    def create(data: dict, user, branch) -> tuple:
        """
        Create an invoice, build line items, compute totals,
        generate PDF and deliver.
        Returns (invoice, errors).
        """
        from decimal import Decimal
        from django.utils import timezone
        from apps.finance.models import Invoice, InvoiceLineItem
        from apps.jobs.models import Job, JobLineItem, Service
        from apps.jobs.pricing_engine import PricingEngine

        job = None
        if data.get('job_id'):
            try:
                job = Job.objects.get(pk=data['job_id'], branch=branch)
            except Job.DoesNotExist:
                return None, ['Job not found.']

        invoice = Invoice.objects.create(
            branch           = branch,
            job              = job,
            generated_by     = user,
            invoice_type     = data['invoice_type'],
            due_date         = data.get('due_date'),
            bm_note          = data.get('bm_note', ''),
            bill_to_name     = data['bill_to_name'],
            bill_to_phone    = data.get('bill_to_phone', ''),
            bill_to_email    = data.get('bill_to_email', ''),
            bill_to_company  = data.get('bill_to_company', ''),
            delivery_channel = data['delivery_channel'],
            vat_rate         = data.get('vat_rate', 0),
            status           = Invoice.DRAFT,
        )

        # ── Build line items ──────────────────────────────────────────
        if job:
            job_items = JobLineItem.objects.filter(
                job=job
            ).select_related('service').order_by('position')

            for i, li in enumerate(job_items):
                InvoiceLineItem.objects.create(
                    invoice    = invoice,
                    service    = li.service,
                    label      = li.label or li.service.name,
                    quantity   = li.quantity,
                    pages      = li.pages,
                    sets       = li.sets,
                    is_color   = li.is_color,
                    paper_size = li.paper_size,
                    sides      = li.sides,
                    unit_price = li.unit_price,
                    line_total = li.line_total,
                    position   = i,
                )
        else:
            for i, item in enumerate(data.get('line_items', [])):
                try:
                    svc = Service.objects.get(pk=item['service'])
                except Service.DoesNotExist:
                    continue

                pg       = int(item.get('pages', 1))
                sets     = int(item.get('sets', 1))
                is_color = bool(item.get('is_color', False))

                pricing    = PricingEngine.get_price(
                    service  = svc,
                    branch   = branch,
                    quantity = sets,
                    is_color = is_color,
                    pages    = pg,
                )
                line_total = Decimal(str(pricing.get('total', 0)))
                unit_price = line_total / (pg * sets) if (pg * sets) > 0 else Decimal('0')

                InvoiceLineItem.objects.create(
                    invoice    = invoice,
                    service    = svc,
                    label      = svc.name,
                    quantity   = sets,
                    pages      = pg,
                    sets       = sets,
                    is_color   = is_color,
                    paper_size = item.get('paper_size', 'A4'),
                    sides      = item.get('sides', 'SINGLE'),
                    unit_price = unit_price,
                    line_total = line_total,
                    position   = i,
                )

        # ── Compute totals ────────────────────────────────────────────
        invoice.compute_totals()
        invoice.save(update_fields=['subtotal', 'vat_amount', 'total', 'updated_at'])

        # ── Generate PDF ──────────────────────────────────────────────
        try:
            from apps.finance.api.views import _generate_invoice_pdf
            _generate_invoice_pdf(invoice)
        except Exception:
            logger.exception('InvoiceService: PDF generation failed for invoice %s', invoice.pk)

        # ── Deliver ───────────────────────────────────────────────────
        try:
            from apps.finance.api.views import _deliver_invoice
            _deliver_invoice(invoice)
        except Exception:
            logger.exception('InvoiceService: delivery failed for invoice %s', invoice.pk)

        return invoice, []