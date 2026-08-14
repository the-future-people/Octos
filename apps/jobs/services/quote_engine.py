"""
Quote engine — proforma invoices and their conversion into jobs.

A quote is a price commitment sent to a customer. Everything here follows
from that:

  - Revisions are new rows, never edits. A customer holding a printed v1
    must be able to accept v1, so v1 has to still exist as a document.
  - Pricing goes through PricingEngine. Manual amounts would be a route
    around the pricing rules, and a quote is the worst place for that
    because the figure is promised to someone.
  - Registered customers only. Conversion needs a real profile for credit
    terms and history, and free text carries none of it.
  - Branch Manager only. Issuing, revising and converting are all price
    commitments on behalf of the branch.

Lifecycle:

    DRAFT -> ISSUED -> CONVERTED
                    -> SUPERSEDED   (revised, new version issued)
                    -> EXPIRED      (21 days, terminal)

Expiry is deliberately terminal. An expired quote is replaced by a new one
at current prices, never revived — otherwise a stale price becomes
negotiable and the 21-day limit means nothing.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

VALIDITY_DAYS = 21

# Roles permitted to issue, revise and convert. Deliberately narrow: this
# is a price commitment made on behalf of the branch.
QUOTE_ROLES = {'BRANCH_MANAGER', 'REGIONAL_MANAGER', 'BELT_MANAGER', 'SUPER_ADMIN'}


class QuoteEngine:

    def __init__(self, branch):
        self.branch = branch

    # ── Guards ───────────────────────────────────────────────────

    @staticmethod
    def _may_quote(actor):
        role = getattr(getattr(actor, 'role', None), 'name', '') or ''
        return role in QUOTE_ROLES

    def _require_permission(self, actor, verb):
        if not self._may_quote(actor):
            raise PermissionError(
                f"{actor.full_name or actor.email} cannot {verb} a quote."
            )

    # ── Pricing ──────────────────────────────────────────────────

    def _price_lines(self, raw_lines):
        """
        Price each requested line through PricingEngine and return the
        stored line_items shape plus the subtotal.

        A pricing failure raises rather than defaulting to zero. Six real
        jobs were once recorded as free because a conditional service
        returned success=False and the caller wrote the zero anyway.
        """
        from apps.jobs.models import Service
        from apps.jobs.pricing_engine import PricingEngine

        priced   = []
        subtotal = Decimal('0.00')

        for line in raw_lines:
            service = Service.objects.get(pk=line['service'])

            condition_params = {}
            if line.get('output_mode'):
                condition_params['output_mode'] = line['output_mode']
            if line.get('ring_size'):
                condition_params['ring_size'] = line['ring_size']

            quantity = int(line.get('quantity', 1))
            pages    = int(line.get('pages', 1))

            result = PricingEngine.get_price(
                service          = service,
                branch           = self.branch,
                quantity         = quantity,
                is_color         = bool(line.get('is_color', False)),
                pages            = pages,
                condition_params = condition_params or None,
            )
            if not result['success']:
                raise ValueError(
                    result.get('error')
                    or f"Could not price {service.name}."
                )

            line_total = Decimal(str(result['total']))
            subtotal  += line_total

            priced.append({
                'service_id'   : service.pk,
                'service_name' : service.name,
                'quantity'     : quantity,
                'pages'        : pages,
                'is_color'     : bool(line.get('is_color', False)),
                'output_mode'  : line.get('output_mode'),
                'ring_size'    : line.get('ring_size'),
                'unit_price'   : str(result.get('base_price', line_total)),
                'total'        : str(line_total),
            })

        return priced, subtotal

    # ── Create ───────────────────────────────────────────────────

    @transaction.atomic
    def create(self, customer, raw_lines, actor, notes='',
               contact_person='', contact_phone='', contact_email=''):
        """Create a DRAFT quote. Nothing is committed to the customer yet."""
        from apps.jobs.models import ProformaInvoice

        self._require_permission(actor, 'create')

        if not raw_lines:
            raise ValueError('A quote needs at least one service.')

        priced, subtotal = self._price_lines(raw_lines)

        number, sequence = ProformaInvoice.generate_proforma_number(
            self.branch.code, timezone.localdate().year,
        )

        return ProformaInvoice.objects.create(
            branch          = self.branch,
            customer        = customer,
            issued_to       = customer.display_name,
            contact_person  = contact_person or '',
            contact_phone   = contact_phone or customer.phone or '',
            contact_email   = contact_email or '',
            proforma_number = number,
            sequence        = sequence,
            version         = 1,
            line_items      = priced,
            subtotal        = subtotal,
            total           = subtotal,
            valid_until     = timezone.localdate() + timedelta(days=VALIDITY_DAYS),
            status          = ProformaInvoice.Status.DRAFT,
            issued_by       = actor,
            notes           = notes,
        )

    # ── Issue ────────────────────────────────────────────────────

    @transaction.atomic
    def issue(self, quote, actor):
        """Send it. The clock starts here."""
        from apps.jobs.models import ProformaInvoice

        self._require_permission(actor, 'issue')

        if quote.status != ProformaInvoice.Status.DRAFT:
            raise ValueError(
                f"{quote.proforma_number} has already been issued."
            )

        quote.status      = ProformaInvoice.Status.ISSUED
        quote.issued_at   = timezone.now()
        quote.valid_until = timezone.localdate() + timedelta(days=VALIDITY_DAYS)
        quote.save(update_fields=[
            'status', 'issued_at', 'valid_until', 'updated_at',
        ])
        return quote

    # ── Revise ───────────────────────────────────────────────────

    @transaction.atomic
    def revise(self, quote, raw_lines, actor, notes=''):
        """
        Issue a new version. The customer never edits anything — they ask,
        the manager revises, and a fresh document goes out.

        This is also how partial acceptance works: a customer taking three
        of five items gets a revision containing those three, so the
        accepted document matches the job exactly.
        """
        from apps.jobs.models import ProformaInvoice

        self._require_permission(actor, 'revise')

        if quote.status not in (ProformaInvoice.Status.DRAFT,
                                ProformaInvoice.Status.ISSUED):
            raise ValueError(
                f"{quote.proforma_number} is {quote.get_status_display().lower()} "
                f"and cannot be revised."
            )
        if quote.is_expired:
            raise ValueError(
                f"{quote.proforma_number} has expired. Raise a new quote at "
                f"current prices."
            )

        priced, subtotal = self._price_lines(raw_lines)

        base = quote.proforma_number.split('-v')[0]

        revision = ProformaInvoice.objects.create(
            branch          = quote.branch,
            customer        = quote.customer,
            issued_to       = quote.issued_to,
            contact_person  = quote.contact_person,
            contact_phone   = quote.contact_phone,
            contact_email   = quote.contact_email,
            proforma_number = f"{base}-v{quote.version + 1}",
            sequence        = quote.sequence,
            version         = quote.version + 1,
            supersedes      = quote,
            line_items      = priced,
            subtotal        = subtotal,
            total           = subtotal,
            issued_at       = timezone.now(),
            valid_until     = timezone.localdate() + timedelta(days=VALIDITY_DAYS),
            status          = ProformaInvoice.Status.ISSUED,
            issued_by       = actor,
            notes           = notes or quote.notes,
        )

        quote.status = ProformaInvoice.Status.SUPERSEDED
        quote.save(update_fields=['status', 'updated_at'])

        return revision

    # ── Convert ──────────────────────────────────────────────────

    @transaction.atomic
    def convert(self, quote, actor, agreed_terms=''):
        """
        The customer accepted. Create the job and put it in front of the
        cashier.

        The job is recorded today, not on the day the quote went out —
        materials are consumed today and revenue must not diverge from the
        sheet that carries the cost. The cashier applies the deposit or the
        credit arrangement; agreed_terms only records what was agreed.
        """
        from apps.jobs.models import Job, JobLineItem, ProformaInvoice, Service
        from apps.finance.sheet_engine import SheetEngine

        self._require_permission(actor, 'convert')

        if not quote.is_convertible:
            if quote.is_expired:
                raise ValueError(
                    f"{quote.proforma_number} expired on {quote.valid_until}. "
                    f"Raise a new quote at current prices."
                )
            raise ValueError(
                f"{quote.proforma_number} is "
                f"{quote.get_status_display().lower()} and cannot be converted."
            )

        sheet, _ = SheetEngine(self.branch).get_or_open_today()
        if sheet is None:
            raise ValueError(
                'No open sheet today, so the job cannot be recorded. '
                'Convert once the branch has opened.'
            )

        names = [li['service_name'] for li in quote.line_items]
        if len(names) == 1:
            title = names[0]
        elif len(names) <= 3:
            title = ', '.join(names)
        else:
            title = ', '.join(names[:3]) + f' +{len(names) - 3} more'

        job = Job.objects.create(
            branch          = self.branch,
            job_type        = 'PRODUCTION',
            status          = Job.PENDING_PAYMENT,
            title           = title,
            customer        = quote.customer,
            intake_by       = actor,
            intake_channel  = 'QUOTE',
            estimated_cost  = quote.total,
            daily_sheet     = sheet,
            payment_state   = 'UNPAID',
            work_state      = 'RECEIVED',
            handover_state  = 'AWAITING_COLLECTION',
            notes           = f"Converted from {quote.proforma_number}.",
        )

        for i, li in enumerate(quote.line_items):
            JobLineItem.objects.create(
                job        = job,
                service    = Service.objects.get(pk=li['service_id']),
                quantity   = li['quantity'],
                pages      = li['pages'],
                is_color   = li['is_color'],
                unit_price = Decimal(li['unit_price']),
                line_total = Decimal(li['total']),
                position   = i,
            )

        quote.status       = ProformaInvoice.Status.CONVERTED
        quote.job          = job
        quote.converted_at = timezone.now()
        quote.converted_by = actor
        quote.agreed_terms = agreed_terms or ''
        quote.save(update_fields=[
            'status', 'job', 'converted_at', 'converted_by',
            'agreed_terms', 'updated_at',
        ])

        from apps.core.broadcast import broadcast_invalidation
        broadcast_invalidation(self.branch.id, [
            'paymentQueue', 'jobs', 'jobStats', 'recentJobs',
            'quotes', 'cashierSummary',
        ])

        return job

    # ── Expiry ───────────────────────────────────────────────────

    @staticmethod
    def expire_stale_quotes():
        """
        Terminal by design. Runs daily; returns the number expired.
        """
        from apps.jobs.models import ProformaInvoice

        stale = ProformaInvoice.objects.filter(
            status=ProformaInvoice.Status.ISSUED,
            valid_until__lt=timezone.localdate(),
        )
        count = stale.count()
        stale.update(status=ProformaInvoice.Status.EXPIRED)
        return count