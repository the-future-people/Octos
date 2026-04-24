# apps/jobs/services/job_service.py
"""
Job services — command-side operations for job creation and management.

Functions:
  save_draft()          — save in-progress cart as DRAFT job
  create_late_job()     — BM post-closing job creation
  create_service()      — create service with pricing rule and consumable mappings

Private helpers:
  _price_line_items()   — shared line-item pricing loop (used by draft + late job)
  _auto_map_toner()     — auto-create toner consumable mappings from paper selection
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


# ── Shared helper ─────────────────────────────────────────────────────────────

def _price_line_items(line_items_data, branch) -> tuple[list, Decimal, list]:
    """
    Price a list of raw line item dicts against branch pricing rules.

    Returns:
        (priced_items, total, names)
        priced_items — list of dicts ready for JobLineItem.objects.create()
        total        — Decimal total estimated cost
        names        — list of service names for title generation
    """
    from apps.jobs.models import Service
    from apps.jobs.pricing_engine import PricingEngine

    priced_items = []
    total        = Decimal('0.00')
    names        = []

    for item in line_items_data:
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
        unit_price = Decimal(str(pricing.get('base_price', 0)))
        total     += line_total
        names.append(svc.name)
        priced_items.append({
            'service'   : svc,
            'pages'     : pg,
            'sets'      : sets,
            'quantity'  : sets,
            'is_color'  : is_color,
            'paper_size': item.get('paper_size', 'A4'),
            'sides'     : item.get('sides', 'SINGLE'),
            'unit_price': unit_price,
            'line_total': line_total,
            'label'     : svc.name,
        })

    return priced_items, total, names


def _build_title(names: list) -> str:
    """Build a job title from a list of service names."""
    if len(names) == 1:
        return names[0]
    elif len(names) <= 3:
        return ', '.join(names)
    else:
        return ', '.join(names[:3]) + f' +{len(names)-3} more'


def _create_line_items(job, priced_items: list):
    """Bulk-create JobLineItem records for a job."""
    from apps.jobs.models import JobLineItem
    for i, item in enumerate(priced_items):
        JobLineItem.objects.create(
            job        = job,
            service    = item['service'],
            quantity   = item['quantity'],
            pages      = item['pages'],
            sets       = item['sets'],
            is_color   = item['is_color'],
            paper_size = item['paper_size'],
            sides      = item['sides'],
            unit_price = item['unit_price'],
            line_total = item['line_total'],
            label      = item.get('label', item['service'].name),
            position   = i,
        )


# ── Service commands ──────────────────────────────────────────────────────────

def save_draft(user, branch, data: dict) -> dict:
    """
    Save an in-progress cart as a DRAFT job.

    Args:
        user   : CustomUser (the attendant)
        branch : Branch instance
        data   : raw request.data dict

    Returns:
        dict — {id, job_number, title, total, expires_at}

    Raises:
        ValueError — branch lock, Sunday block, no valid line items
    """
    from apps.jobs.models import Job
    from apps.finance.sheet_engine import SheetEngine
    from apps.customers.models import CustomerProfile
    from django.utils import timezone
    from datetime import timedelta

    if timezone.localdate().weekday() == 6:
        raise ValueError('Branch is closed on Sundays. No jobs can be recorded.')

    lock = SheetEngine(branch).get_branch_lock_status()
    if not lock['can_create_jobs']:
        raise ValueError(lock['lock_reason'])

    line_items_data = data.get('line_items', [])
    if not line_items_data:
        raise ValueError('No line items to save.')

    priced_items, total, names = _price_line_items(line_items_data, branch)
    if not priced_items:
        raise ValueError('No valid line items.')

    customer = None
    customer_id = data.get('customer')
    if customer_id:
        try:
            customer = CustomerProfile.objects.get(pk=customer_id)
        except CustomerProfile.DoesNotExist:
            pass

    sheet, _ = SheetEngine(branch).get_or_open_today()

    now     = timezone.now()
    expires = now + timedelta(days=3)

    job = Job.objects.create(
        branch           = branch,
        intake_by        = user,
        customer         = customer,
        title            = _build_title(names),
        job_type         = 'INSTANT',
        status           = Job.DRAFT,
        estimated_cost   = total,
        daily_sheet      = sheet,
        draft_expires_at = expires,
    )
    _create_line_items(job, priced_items)

    return {
        'id'        : job.id,
        'job_number': job.job_number,
        'title'     : job.title,
        'total'     : str(total),
        'expires_at': expires.isoformat(),
    }


def create_late_job(user, branch, data: dict):
    """
    BM creates a post-closing job after branch closing time.

    Args:
        user   : CustomUser (must be BRANCH_MANAGER)
        branch : Branch instance
        data   : raw request.data dict

    Returns:
        Job instance

    Raises:
        PermissionError — not a BM
        ValueError      — branch still open, missing reason, no valid items, no sheet
    """
    from apps.jobs.models import Job
    from apps.finance.sheet_engine import SheetEngine
    from apps.hr.shift_engine import ShiftEngine as HRShiftEngine

    role_name = getattr(getattr(user, 'role', None), 'name', '')
    if role_name != 'BRANCH_MANAGER':
        raise PermissionError('Only a Branch Manager can create post-closing jobs.')

    bm_schedule = HRShiftEngine(branch).get_role_schedule('BRANCH_MANAGER')
    if bm_schedule['can_create_jobs'] and not bm_schedule['is_post_closing']:
        raise ValueError('Branch is still open. Use the standard New Job flow.')

    reason = data.get('post_closing_reason', '').strip()
    if not reason:
        raise ValueError('A reason is required for post-closing jobs.')

    line_items_data = data.get('line_items', [])
    if not line_items_data:
        raise ValueError('At least one service is required.')

    sheet, _ = SheetEngine(branch).get_or_open_today()
    if not sheet:
        raise ValueError('No active sheet for today.')

    priced_items, total, names = _price_line_items(line_items_data, branch)
    if not priced_items:
        raise ValueError('No valid services found.')

    job = Job.objects.create(
        branch                   = branch,
        intake_by                = user,
        daily_sheet              = sheet,
        title                    = _build_title(names),
        job_type                 = 'INSTANT',
        status                   = Job.PENDING_PAYMENT,
        estimated_cost           = total,
        post_closing             = True,
        post_closing_reason      = reason,
        post_closing_approved_by = user,
        intake_channel           = data.get('intake_channel', 'WALK_IN'),
    )
    _create_line_items(job, priced_items)

    return job


# ── Service creation ──────────────────────────────────────────────────────────

def create_service(user, branch, validated_data: dict, raw_mappings_json: str = None):
    """
    Create a new Service with pricing rule and optional consumable mappings.

    Args:
        user              : CustomUser
        branch            : Branch instance (or None)
        validated_data    : dict from ServiceCreateSerializer.validated_data
        raw_mappings_json : raw JSON string from multipart request.data

    Returns:
        Service instance
    """
    import json
    from apps.jobs.models import Service, PricingRule

    d     = validated_data
    sides = d.get('sides', 'SINGLE')

    service = Service.objects.create(
        name           = d['name'],
        code           = d['code'],
        category       = d['category'],
        unit           = d['unit'],
        description    = d['description'],
        image          = d.get('image'),
        is_active      = True,
        smart_defaults = {
            'sides'   : sides,
            'pages'   : 1,
            'sets'    : 1,
            'is_color': 'color' in d['name'].lower() or 'colour' in d['name'].lower(),
        },
    )

    if branch:
        PricingRule.objects.create(
            service    = service,
            branch     = branch,
            base_price = d['base_price'],
            is_active  = True,
        )

    mappings_data = []
    if raw_mappings_json and isinstance(raw_mappings_json, str):
        try:
            mappings_data = json.loads(raw_mappings_json)
        except json.JSONDecodeError:
            mappings_data = []

    if mappings_data:
        from apps.inventory.models import ConsumableItem, ServiceConsumable
        for mapping in mappings_data:
            try:
                consumable = ConsumableItem.objects.get(pk=mapping['consumable_id'])
                ServiceConsumable.objects.get_or_create(
                    service    = service,
                    consumable = consumable,
                    defaults   = {
                        'quantity_per_unit': mapping['quantity_per_unit'],
                        'applies_to_color' : mapping.get('applies_to_color', True),
                        'applies_to_bw'    : mapping.get('applies_to_bw', True),
                    }
                )
            except ConsumableItem.DoesNotExist:
                pass

    _auto_map_toner(service, mappings_data, sides=sides)

    return service


def _auto_map_toner(service, manual_mappings, sides='SINGLE'):
    """
    Auto-create toner ServiceConsumable mappings based on paper selection.

    Rules:
      A5 paper → 0.005 toner per page
      A4 paper → 0.01  toner per page
      A3 paper → 0.02  toner per page
      Color services  → all 4 toners (CMYK)
      B&W services    → black toner only
      Ambiguous name  → both
    """
    from apps.inventory.models import ConsumableItem, ServiceConsumable

    selected_ids = [m['consumable_id'] for m in (manual_mappings or [])]
    if not selected_ids:
        return

    paper_consumables = ConsumableItem.objects.filter(
        id__in         = selected_ids,
        category__name = 'Paper',
    ).exclude(unit_type='PERCENT')

    if not paper_consumables.exists():
        return

    TONER_RATES = {'A5': 0.005, 'A4': 0.01, 'A3': 0.02, 'A2': 0.04}

    name_lower    = service.name.lower()
    is_color_name = 'color' in name_lower or 'colour' in name_lower
    is_bw_name    = 'b&w' in name_lower or 'bw' in name_lower or 'black' in name_lower

    if is_color_name and not is_bw_name:
        applies_color, applies_bw = True, False
    elif is_bw_name and not is_color_name:
        applies_color, applies_bw = False, True
    else:
        applies_color, applies_bw = True, True

    black_toner   = ConsumableItem.objects.filter(name__icontains='Toner Black').first()
    cyan_toner    = ConsumableItem.objects.filter(name__icontains='Toner Cyan').first()
    magenta_toner = ConsumableItem.objects.filter(name__icontains='Toner Magenta').first()
    yellow_toner  = ConsumableItem.objects.filter(name__icontains='Toner Yellow').first()

    for paper in paper_consumables:
        rate = TONER_RATES.get(paper.paper_size, 0.01)
        if sides == 'DOUBLE':
            rate = rate * 2
        toners = [black_toner]
        if applies_color:
            toners = [black_toner, cyan_toner, magenta_toner, yellow_toner]

        for toner in toners:
            if not toner:
                continue
            ServiceConsumable.objects.get_or_create(
                service    = service,
                consumable = toner,
                defaults   = {
                    'quantity_per_unit': rate,
                    'applies_to_color' : applies_color,
                    'applies_to_bw'    : applies_bw,
                }
            )