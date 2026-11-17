"""
What work costs to make (17 Nov 2026), from CostSettings.

A page's cost is its paper plus its toner, plus a share for machine wear:

    paper  = box price / sheets in the box
    black  = black toner price / pages it prints x coverage
    colour = black + 3 x (colour toner price / pages it prints x coverage)
    page   = (paper + toner x sides on the sheet) x size against A4 x (1 + wear)

Canon rates toner yields at 5% cover; coverage says how much more a typical
page uses (3 for charts and pictures). With the defaults an A4 colour page
costs about GHS 0.74 and a black and white one about GHS 0.27.

A job's cost is known only when every line has a cost; otherwise the known
part is returned with known=False, and discounts are held to a percentage.
"""
from decimal import Decimal

THREE = Decimal('3')
CENT = Decimal('0.01')


def page_costs(settings=None):
    """{'paper', 'black', 'colour'} for one A4 side, before wear."""
    from apps.jobs.models import CostSettings
    s = settings or CostSettings.current()
    paper = s.paper_box_price / max(s.paper_box_sheets, 1)
    black = s.toner_black_price / max(s.toner_black_pages, 1) * s.coverage
    colour = black + THREE * s.toner_colour_price / max(s.toner_colour_pages, 1) * s.coverage
    return {'paper': paper, 'black': black, 'colour': colour, 'wear': s.wear_percent / 100}


def unit_cost(service, settings=None, costs=None):
    """What one priced unit of this service costs to make, or None when not set."""
    from apps.jobs.models import Service
    from apps.jobs.services.availability import pages_per_sheet

    basis = service.cost_basis
    if basis == Service.COST_FIXED:
        return service.cost_amount
    if basis not in (Service.COST_COLOUR, Service.COST_BW):
        return None
    c = costs or page_costs(settings)
    toner = c['colour'] if basis == Service.COST_COLOUR else c['black']
    sheet = (c['paper'] + toner * pages_per_sheet(service)) * service.cost_size * (1 + c['wear'])
    return sheet


def line_cost(service, pages, copies, costs=None):
    """(cost, known) of one line: pages of one copy, so many copies."""
    from apps.jobs.models import Service
    from apps.jobs.pricing_engine import sheets_of

    each = unit_cost(service, costs=costs)
    if each is None:
        return Decimal('0'), False
    copies = max(int(copies or 1), 1)
    if service.cost_basis == Service.COST_FIXED:
        return each * copies, True
    return each * sheets_of(service, pages) * copies, True


def _page_line(service):
    from apps.jobs.models import Service
    return service.cost_basis in (Service.COST_COLOUR, Service.COST_BW) or \
        (service.unit or '').upper().replace('PER_', '') in ('COPY', 'PAGE', 'SHEET')


def job_cost(job):
    """
    {'cost', 'known', 'page_units', 'page_total'} for a job: its cost to make,
    whether every line has a cost, and how many priced pages (sheets x
    copies) its page lines hold and what they come to, so a new price can
    be given a page at a time.
    """
    from apps.jobs.pricing_engine import sheets_of

    costs = page_costs()
    total, known, units, page_total = Decimal('0'), True, 0, Decimal('0')
    for line in job.line_items.select_related('service'):
        if line.service is None:
            known = False
            continue
        if line.parent_id:
            cost, ok = line_cost(line.service, 1, line.quantity, costs)
        else:
            copies = line.sets or line.quantity or 1
            cost, ok = line_cost(line.service, line.pages, copies, costs)
            if _page_line(line.service):
                units += sheets_of(line.service, line.pages) * copies
                page_total += line.line_total or 0
        total += cost
        known = known and ok
    if not job.line_items.exists():
        known = False
    return {'cost': total.quantize(CENT), 'known': known, 'page_units': units, 'page_total': page_total}


def proforma_cost(proforma):
    """The same for a proforma, from its stored lines."""
    from apps.jobs.models import Service
    from apps.jobs.pricing_engine import sheets_of

    costs = page_costs()
    services = {s.pk: s for s in Service.objects.filter(pk__in=_service_ids(proforma.line_items))}
    total, known, units, page_total = Decimal('0'), bool(proforma.line_items), 0, Decimal('0')
    for line in proforma.line_items or []:
        service = services.get(line.get('service_id'))
        copies = int(line.get('quantity') or 1)
        pages = int(line.get('pages') or 1)
        if service is None:
            known = False
            continue
        cost, ok = line_cost(service, pages, copies, costs)
        total += cost
        known = known and ok
        if _page_line(service):
            units += sheets_of(service, pages) * copies
            page_total += Decimal(str(line.get('own_total') or line.get('total') or 0))
        for addon in line.get('addons') or []:
            extra = services.get(addon.get('service'))
            if extra is None:
                known = False
                continue
            cost, ok = line_cost(extra, 1, addon.get('quantity') or 1, costs)
            total += cost
            known = known and ok
    return {'cost': total.quantize(CENT), 'known': known, 'page_units': units, 'page_total': page_total}


def _service_ids(lines):
    ids = set()
    for line in lines or []:
        ids.add(line.get('service_id'))
        ids.update(a.get('service') for a in line.get('addons') or [])
    return {i for i in ids if i}
