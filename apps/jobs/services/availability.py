"""
Whether a service can be made, and what its add-ons cost.

Available is worked out, never set by hand: a service can be made when
it has a price and every machine its route needs exists at the branch.
So a clear bag with no price yet shows as unavailable, a DTF shirt is
"coming soon" until a DTF printer is added, and both switch on by
themselves the day the price or the machine arrives. A machine that is
merely down for the afternoon does not count against it: that is the
floor's business, not the catalogue's.

An add-on is an ordinary service (lamination, binding, an envelope)
offered alongside another. It is priced by its own rule. Lamination is
counted in sheets, everything else in copies.
"""

from decimal import Decimal

from django.db.models import Q

# Units the live catalogue uses for "per sheet". Choices are not enforced
# on save, so the data holds more spellings than the model lists.
SHEET_UNITS = {'sheet', 'PER_PAGE', 'PER_SHEET'}


def has_price(service, branch=None):
    from apps.jobs.models import PricingRule
    rules = PricingRule.objects.filter(service=service, is_active=True)
    if branch is not None:
        rules = rules.filter(Q(branch__isnull=True) | Q(branch=branch))
    return rules.exists()


def has_machines(service, branch=None):
    """Every machine type on the route exists, at this branch or any."""
    from apps.production.models import Machine, ServiceStation

    needed = (
        ServiceStation.objects
        .filter(service=service, machine_type__isnull=False)
        .values_list('machine_type_id', flat=True)
        .distinct()
    )
    for machine_type_id in needed:
        machines = Machine.objects.filter(machine_type_id=machine_type_id, is_active=True)
        if branch is not None:
            machines = machines.filter(branch=branch)
        if not machines.exists():
            return False
    return True


def can_make(service, branch=None):
    return bool(service.is_active and has_price(service, branch) and has_machines(service, branch))


def display_price(service):
    """The base rate, for showing beside an add-on. None where there is none."""
    from apps.jobs.models import PricingRule
    rule = (
        PricingRule.objects
        .filter(service=service, is_active=True, branch__isnull=True)
        .first()
    ) or PricingRule.objects.filter(service=service, is_active=True).first()
    return f'{rule.base_price:.2f}' if rule else None


def addon_quantity(addon, quantity, specs):
    """Sheets for lamination (copies × pages), copies for everything else."""
    pages = int((specs or {}).get('pages') or 1)
    return quantity * pages if addon.unit in SHEET_UNITS else quantity


def price_addons(service, chosen, quantity, specs):
    """
    The add-ons chosen for a line, priced. Returns (priced, total, problem).

    chosen holds add-on ids, or the priced add-ons already on a line (each
    a dict with 'service'), so a cart can be re-priced as it stands.
    """
    from apps.jobs.pricing_engine import quote_line

    if not chosen:
        return [], Decimal('0.00'), None
    if not isinstance(chosen, list):
        return None, None, 'Add-ons must be a list.'

    offered = {a.pk: a for a in service.addons.filter(is_active=True)}
    priced, total, seen = [], Decimal('0.00'), set()

    for raw in chosen:
        raw_id = raw.get('service') if isinstance(raw, dict) else raw
        try:
            addon_id = int(raw_id)
        except (TypeError, ValueError):
            return None, None, 'That add-on is not offered.'
        if addon_id in seen:
            continue
        seen.add(addon_id)

        addon = offered.get(addon_id)
        if addon is None:
            return None, None, f'That add-on is not offered with {service.name}.'
        if not can_make(addon):
            return None, None, f'{addon.name} is not available yet.'

        count = addon_quantity(addon, quantity, specs)
        # Sheets are already counted; binding's tiers need the pages.
        addon_specs = {} if addon.unit in SHEET_UNITS else {'pages': int((specs or {}).get('pages') or 1)}
        quote = quote_line(service=addon, branch=None, specifications=addon_specs, quantity=count)
        if not quote.get('success'):
            return None, None, quote.get('error', f'{addon.name} could not be priced.')

        priced.append({
            'service':      addon.pk,
            'service_name': addon.name,
            'quantity':     count,
            'unit_price':   str(quote.get('unit_price') or quote['total']),
            'total':        str(quote['total']),
        })
        total += Decimal(str(quote['total']))

    return priced, total, None


# ── Sheets from the customer's file ──────────────────────────────

# The version printed on both sides of each sheet.
DOUBLE_SIDED = 'Front and back'


def pages_per_sheet(service):
    return 2 if (service.variant_label or '').strip() == DOUBLE_SIDED else 1


def counts_pages(service):
    """A service priced by the sheet from a file the customer sends."""
    return bool(service.requires_file_upload) and any(
        f.get('key') == 'pages' for f in (service.spec_template or [])
    )


def sheets_for(service, page_count):
    """
    Sheets per copy for a file of this many pages. The customer never
    types it: the file says how many pages it has, and the sides say how
    many pages a sheet holds. A photo or image is one page.
    """
    pages = max(1, int(page_count or 1))
    per = pages_per_sheet(service)
    return (pages + per - 1) // per