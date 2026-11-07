"""
Proforma engine — proforma invoices and their conversion into jobs.

"Proforma" is used throughout, in the code and in the interface, because
it is the word customers use. Institutional procurement asks for a
proforma by name; a second internal word for the same document would need
translating by whoever is covering the counter.

A proforma is a price commitment sent to a customer. Everything here
follows from that:

  - Revisions are new rows, never edits. A customer holding a printed v1
    must be able to accept v1, so v1 has to still exist as a document.
  - Pricing goes through PricingEngine. Manual amounts would be a route
    around the pricing rules, and a proforma is the worst place for that
    because the figure is promised to someone.
  - Registered customers only. Conversion needs a real profile for credit
    terms and history, and free text carries none of it.
  - Branch Manager only. Issuing, revising and converting are all price
    commitments on behalf of the branch.

Lifecycle:

    DRAFT -> ISSUED -> CONVERTED
                    -> SUPERSEDED   (revised, new version issued)
                    -> EXPIRED      (21 days, terminal)

Expiry is deliberately terminal. An expired proforma is replaced by a new one
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
# OCTOS (7 Nov 2026): Octos's own account. Its prices come only from the
# engine, never typed, which is what this rule guards against.
PROFORMA_ROLES = {'BRANCH_MANAGER', 'REGIONAL_MANAGER', 'BELT_MANAGER', 'SUPER_ADMIN', 'OCTOS'}


class ProformaEngine:

    def __init__(self, branch):
        self.branch = branch

    # ── Guards ───────────────────────────────────────────────────

    @staticmethod
    def _may_issue(actor):
        role = getattr(getattr(actor, 'role', None), 'name', '') or ''
        return role in PROFORMA_ROLES

    def _require_permission(self, actor, verb):
        if not self._may_issue(actor):
            raise PermissionError(
                f"{actor.full_name or actor.email} cannot {verb} a proforma."
            )

    # ── Pricing ──────────────────────────────────────────────────

    def _price_lines(self, raw_lines):
        """
        Price each requested line and return the stored line_items shape
        plus the subtotal.

        Through quote_line() and price_addons(), the path every other quote
        takes (7 Nov 2026): both sides counted in sheets, banner sizes made
        into an area, a product's minimum, and add-ons. A proforma and a
        quote for the same job always agree.

        A pricing failure raises rather than defaulting to zero. Six real
        jobs were once recorded as free because a conditional service
        returned success=False and the caller wrote the zero anyway.
        """
        from apps.jobs.models import Service
        from apps.jobs.pricing_engine import quote_line
        from apps.jobs.services.availability import price_addons

        priced   = []
        subtotal = Decimal('0.00')

        for line in raw_lines:
            service  = Service.objects.get(pk=line['service'])
            quantity = int(line.get('quantity') or 1)
            pages    = int(line.get('pages') or 1)

            specs = dict(line.get('specifications') or {})
            specs['pages'] = pages
            for key in ('width_in', 'height_in', 'ring_size', 'output_mode'):
                if line.get(key) not in (None, ''):
                    specs[key] = line[key]
            if line.get('is_color'):
                specs['is_color'] = True

            result = quote_line(service, self.branch, specs, quantity)
            if not result.get('success'):
                raise ValueError(result.get('error') or f"Could not price {service.name}.")
            own = Decimal(str(result['total']))

            addons, addons_total = [], Decimal('0.00')
            if line.get('addons'):
                extras, extras_total, problem = price_addons(service, list(line['addons']), quantity, specs)
                if problem:
                    raise ValueError(problem)
                addons = [{'service': e['service'], 'service_name': e['service_name'],
                           'quantity': e['quantity'], 'detail': e.get('detail'),
                           'unit_price': e['unit_price'], 'total': e['total']} for e in extras]
                addons_total = Decimal(str(extras_total))

            line_total = own + addons_total
            subtotal  += line_total
            name = service.name
            if addons:
                name += ' + ' + ', '.join(
                    a['service_name'] + (f" ({a['detail']})" if a.get('detail') else '') for a in addons)

            priced.append({
                'service_id'     : service.pk,
                'service_name'   : name,
                'quantity'       : quantity,
                'pages'          : pages,
                'is_color'       : bool(specs.get('is_color')),
                'output_mode'    : line.get('output_mode'),
                'ring_size'      : line.get('ring_size'),
                'specifications' : {k: (str(v) if isinstance(v, Decimal) else v)
                                    for k, v in specs.items() if k != 'pages'},
                'addons'         : addons,
                'own_total'      : str(own),
                'unit_price'     : str((line_total / quantity).quantize(Decimal('0.01'))),
                'total'          : str(line_total),
            })

        return priced, subtotal

    # ── Create ───────────────────────────────────────────────────

    @transaction.atomic
    def create(self, customer, raw_lines, actor, notes='',
               contact_person='', contact_phone='', contact_email=''):
        """Create a DRAFT proforma. Nothing is committed to the customer yet."""
        from apps.jobs.models import ProformaInvoice

        self._require_permission(actor, 'create')

        if not raw_lines:
            raise ValueError('A proforma needs at least one service.')

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
    def issue(self, proforma, actor):
        """Send it. The clock starts here."""
        from apps.jobs.models import ProformaInvoice

        self._require_permission(actor, 'issue')

        if proforma.status != ProformaInvoice.Status.DRAFT:
            raise ValueError(
                f"{proforma.proforma_number} has already been issued."
            )

        proforma.status      = ProformaInvoice.Status.ISSUED
        proforma.issued_at   = timezone.now()
        proforma.valid_until = timezone.localdate() + timedelta(days=VALIDITY_DAYS)
        proforma.save(update_fields=[
            'status', 'issued_at', 'valid_until', 'updated_at',
        ])
        return proforma

    # ── Revise ───────────────────────────────────────────────────

    @transaction.atomic
    def revise(self, proforma, raw_lines, actor, notes=''):
        """
        Issue a new version. The customer never edits anything — they ask,
        the manager revises, and a fresh document goes out.

        This is also how partial acceptance works: a customer taking three
        of five items gets a revision containing those three, so the
        accepted document matches the job exactly.
        """
        from apps.jobs.models import ProformaInvoice

        self._require_permission(actor, 'revise')

        # A service withdrawn since issue means the branch no longer offers
        # it. Patching the document around the hole would send a customer a
        # revision that quietly dropped something they asked for, so the
        # whole proforma is refused and a fresh one is raised at current
        # prices instead.
        from apps.jobs.models import Service
        quoted_ids = {li['service_id'] for li in proforma.line_items}
        live_ids   = set(
            Service.objects
            .filter(pk__in=quoted_ids, is_active=True)
            .values_list('pk', flat=True)
        )
        withdrawn = quoted_ids - live_ids
        if withdrawn:
            names = ', '.join(
                li['service_name'] for li in proforma.line_items
                if li['service_id'] in withdrawn
            )
            raise ValueError(
                f"{proforma.proforma_number} quotes a service no longer "
                f"offered ({names}). Raise a new proforma instead."
            )

        if proforma.status not in (ProformaInvoice.Status.DRAFT,
                                ProformaInvoice.Status.ISSUED):
            raise ValueError(
                f"{proforma.proforma_number} is {proforma.get_status_display().lower()} "
                f"and cannot be revised."
            )
        if proforma.is_expired:
            raise ValueError(
                f"{proforma.proforma_number} has expired. Raise a new proforma at "
                f"current prices."
            )

        priced, subtotal = self._price_lines(raw_lines)

        base = proforma.proforma_number.split('-v')[0]

        revision = ProformaInvoice.objects.create(
            branch          = proforma.branch,
            customer        = proforma.customer,
            issued_to       = proforma.issued_to,
            contact_person  = proforma.contact_person,
            contact_phone   = proforma.contact_phone,
            contact_email   = proforma.contact_email,
            proforma_number = f"{base}-v{proforma.version + 1}",
            sequence        = proforma.sequence,
            version         = proforma.version + 1,
            supersedes      = proforma,
            line_items      = priced,
            subtotal        = subtotal,
            total           = subtotal,
            issued_at       = timezone.now(),
            valid_until     = timezone.localdate() + timedelta(days=VALIDITY_DAYS),
            status          = ProformaInvoice.Status.ISSUED,
            issued_by       = actor,
            notes           = notes or proforma.notes,
        )

        proforma.status = ProformaInvoice.Status.SUPERSEDED
        proforma.save(update_fields=['status', 'updated_at'])

        return revision

    # ── Convert ──────────────────────────────────────────────────

    @transaction.atomic
    def convert(self, proforma, actor, agreed_terms=''):
        """
        The customer accepted. Create the job and put it in front of the
        cashier.

        The job is recorded today, not on the day the proforma went out —
        materials are consumed today and revenue must not diverge from the
        sheet that carries the cost. The cashier applies the deposit or the
        credit arrangement; agreed_terms only records what was agreed.
        """
        from apps.jobs.models import Job, JobLineItem, ProformaInvoice, Service
        from apps.finance.sheet_engine import SheetEngine

        self._require_permission(actor, 'convert')

        if not proforma.is_convertible:
            if proforma.is_expired:
                raise ValueError(
                    f"{proforma.proforma_number} expired on {proforma.valid_until}. "
                    f"Raise a new proforma at current prices."
                )
            raise ValueError(
                f"{proforma.proforma_number} is "
                f"{proforma.get_status_display().lower()} and cannot be converted."
            )

        sheet, _ = SheetEngine(self.branch).get_or_open_today()
        if sheet is None:
            raise ValueError(
                'No open sheet today, so the job cannot be recorded. '
                'Convert once the branch has opened.'
            )

        names = [li['service_name'] for li in proforma.line_items]
        if len(names) == 1:
            title = names[0]
        elif len(names) <= 3:
            title = ', '.join(names)
        else:
            title = ', '.join(names[:3]) + f' +{len(names) - 3} more'

        # An all-instant proforma is instant work ordered ahead, and typing
        # it as production would put it on a work ladder it never travels.
        # Anything with a production or design line is production.
        from apps.jobs.services.job_service import derive_job_type
        line_service_ids = [li['service_id'] for li in proforma.line_items]
        job_type = derive_job_type(
            Service.objects.filter(pk__in=line_service_ids)
        )

        job = Job.objects.create(
            branch          = self.branch,
            job_type        = job_type,
            status          = Job.PENDING_PAYMENT,
            title           = title,
            customer        = proforma.customer,
            intake_by       = actor,
            intake_channel  = Job.PROFORMA,
            estimated_cost  = proforma.total,
            daily_sheet     = sheet,
            payment_state   = 'UNPAID',
            work_state      = 'RECEIVED',
            handover_state  = 'AWAITING_COLLECTION',
            notes           = f"Converted from {proforma.proforma_number}.",
        )

        for i, li in enumerate(proforma.line_items):
            # The line's own price, and its add-ons as finishing on it (child
            # lines, as the counter records them), with its sizes, so the
            # floor gets what was quoted (7 Nov 2026). Older proformas carry
            # no add-ons and their total is the line's own.
            own = Decimal(li.get('own_total') or li['total'])
            line = JobLineItem.objects.create(
                job            = job,
                service        = Service.objects.get(pk=li['service_id']),
                quantity       = li['quantity'],
                pages          = li['pages'],
                is_color       = li['is_color'],
                specifications = li.get('specifications') or {},
                unit_price     = (own / max(1, int(li['quantity']))).quantize(Decimal('0.01')),
                line_total     = own,
                position       = i,
            )
            for a in li.get('addons') or []:
                JobLineItem.objects.create(
                    job        = job,
                    parent     = line,
                    service    = Service.objects.get(pk=a['service']),
                    quantity   = a['quantity'],
                    pages      = 1,
                    is_color   = False,
                    unit_price = Decimal(str(a['unit_price'])),
                    line_total = Decimal(str(a['total'])),
                    position   = i,
                )

        proforma.status       = ProformaInvoice.Status.CONVERTED
        proforma.job          = job
        proforma.converted_at = timezone.now()
        proforma.converted_by = actor
        proforma.agreed_terms = agreed_terms or ''
        proforma.save(update_fields=[
            'status', 'job', 'converted_at', 'converted_by',
            'agreed_terms', 'updated_at',
        ])

        from apps.core.broadcast import broadcast_invalidation
        broadcast_invalidation(self.branch.id, [
            'paymentQueue', 'jobs', 'jobStats', 'recentJobs',
            'proformas', 'cashierSummary',
        ])

        return job

    # ── Expiry ───────────────────────────────────────────────────

    @staticmethod
    def expire_stale_proformas():
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