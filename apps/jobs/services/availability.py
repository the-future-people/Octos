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
counted in sheets, everything else in copies; binding's price is the
tier for the ring a copy needs.
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


# Packing (an envelope, a bag). Whether copies share one or each gets its
# own is the customer's to say: five application letters going to five
# employers want five envelopes; ten copies of a notice for one office
# want one. Octos only suggests: one for all when a copy is a single
# sheet, one per copy when each copy is a set of several.
PACKING = {'ENV-PACK-A4', 'CLEAR-BAG'}


def is_packing(addon):
    return addon.code in PACKING


def addon_quantity(addon, quantity, specs, per_copy=None):
    """
    Sheets for lamination (copies × sheets); for packing, copies or one as
    the customer chose; copies for everything else.
    """
    sheets = int((specs or {}).get('pages') or 1)
    if addon.unit in SHEET_UNITS:
        return quantity * sheets
    if is_packing(addon):
        if per_copy is None:
            per_copy = sheets > 1
        return quantity if per_copy else 1
    return quantity


# How many 80gsm sheets a comb ring holds, smallest ring first. The
# shop's smallest ring is 8mm, so it is where the chart starts.
RING_CAPACITY = [
    (45, 8), (65, 10), (95, 12), (120, 14), (145, 16), (165, 19),
    (200, 22), (240, 25), (270, 28), (300, 32), (340, 38), (425, 45), (500, 51),
]


def ring_size_for(sheets):
    """The ring a copy of this many sheets needs, or None when too thick."""
    for capacity, ring in RING_CAPACITY:
        if sheets <= capacity:
            return ring
    return None


def _conditions_of(addon):
    """The conditions an add-on's price tiers are chosen by (ring size)."""
    from apps.jobs.models import PricingRule
    rule = PricingRule.objects.filter(service=addon, is_active=True).first()
    tiers = (rule.pricing_tiers or []) if rule else []
    return {t.get('condition') for t in tiers if isinstance(t, dict) and t.get('condition')}


def price_addons(service, chosen, quantity, specs):
    """
    The add-ons chosen for a line, priced. Returns (priced, total, problem).

    chosen holds add-on ids, or dicts with 'service' (and, for packing,
    'per_copy'), so a cart can be re-priced as it stands and a packing
    choice survives a change of quantity.

    How each is counted:
      - by the sheet (lamination): sheets × copies
      - by the copy (envelope, binding): copies, the page count never
        multiplies it
      - binding's price is the tier for the ring one copy needs, and the
        ring is chosen from the sheets in a copy
    """
    from apps.jobs.pricing_engine import quote_line

    if not chosen:
        return [], Decimal('0.00'), None
    if not isinstance(chosen, list):
        return None, None, 'Add-ons must be a list.'

    offered = {a.pk: a for a in service.addons.filter(is_active=True)}
    sheets = int((specs or {}).get('pages') or 1)
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

        per_copy = raw.get('per_copy') if isinstance(raw, dict) else None
        if is_packing(addon) and per_copy is None:
            per_copy = sheets > 1
        count = addon_quantity(addon, quantity, specs, per_copy)

        # Only what chooses a tier is passed. Pages are never passed: the
        # engine multiplies by them, which is how an envelope became
        # GHS 2 × pages × copies.
        addon_specs = {}
        detail = None
        if 'ring_size' in _conditions_of(addon):
            ring = ring_size_for(sheets)
            if ring is None:
                return None, None, (
                    f'{sheets} sheets is too thick to ring-bind. '
                    f'Walk in and we will bind it another way.'
                )
            addon_specs['ring_size'] = ring
            detail = f'{ring}mm ring'
        elif is_packing(addon) and quantity > 1:
            detail = 'one per copy' if per_copy else 'one for all copies'

        quote = quote_line(service=addon, branch=None, specifications=addon_specs, quantity=count)
        if not quote.get('success'):
            return None, None, quote.get('error', f'{addon.name} could not be priced.')

        priced.append({
            'service':      addon.pk,
            'service_name': addon.name,
            'quantity':     count,
            'detail':       detail,
            'per_copy':     bool(per_copy) if is_packing(addon) else None,
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