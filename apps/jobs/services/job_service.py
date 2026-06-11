# apps/jobs/services/job_service.py
"""
Job services — command-side operations for job creation and management.

Functions:
  save_draft()          — save in-progress cart as DRAFT job
  create_late_job()     — BM post-closing job creation
  create_service()      — create service with pricing rule and consumable mappings

Private helpers:
  _price_line_items()   — shared line-item pricing loop (used by draft + late job)
  _validate_line_items() — validate line items before pricing
  _auto_map_toner()     — auto-create toner consumable mappings from paper selection
  _build_title()        — generate job title from service names
  _create_line_items()  — bulk create JobLineItem records
  _validate_user_branch() — ensure user belongs to the correct branch
"""

import logging
import json
from decimal import Decimal, InvalidOperation
from typing import List, Tuple, Dict, Any, Optional

from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError

from apps.core.broadcast import broadcast_invalidation

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

DRAFT_EXPIRY_DAYS = 3
MAX_LINE_ITEMS = 20
MAX_POST_CLOSING_REASON_LENGTH = 500
MAX_SERVICE_NAME_LENGTH = 100
VALID_PAPER_SIZES = ['A3', 'A4', 'A5', 'A2', 'LETTER', 'LEGAL']
VALID_SIDES = ['SINGLE', 'DOUBLE']

# ── Validation helpers ───────────────────────────────────────────────────────

def _validate_user_branch(user, branch) -> None:
    """
    Validate that user belongs to the specified branch.
    
    Raises:
        PermissionError: If user doesn't belong to the branch
        ValueError: If user is not active
    """
    if not user or not user.is_active:
        raise ValueError('User account is not active.')
    
    if hasattr(user, 'branch') and user.branch_id:
        if user.branch_id != branch.id:
            raise PermissionError(
                f'User {user.full_name} does not belong to branch {branch.name}.'
            )


def _validate_line_items(line_items_data: List[Dict]) -> None:
    """
    Validate line items before pricing.
    
    Raises:
        ValueError: If line items are invalid
    """
    if not line_items_data:
        raise ValueError('No line items provided.')
    
    if len(line_items_data) > MAX_LINE_ITEMS:
        raise ValueError(
            f'Too many line items. Maximum {MAX_LINE_ITEMS} allowed.'
        )
    
    for i, item in enumerate(line_items_data):
        if not isinstance(item, dict):
            raise ValueError(f'Line item {i} must be a dictionary.')
        
        if 'service' not in item:
            raise ValueError(f'Line item {i} is missing required field: service.')
        
        # Validate numeric fields
        pages = item.get('pages', 1)
        sets = item.get('sets', 1)
        
        try:
            pages = int(pages)
            sets = int(sets)
        except (ValueError, TypeError):
            raise ValueError(f'Line item {i}: pages and sets must be valid integers.')
        
        if pages < 1 or pages > 10000:
            raise ValueError(
                f'Line item {i}: pages must be between 1 and 10,000.'
            )
        
        if sets < 1 or sets > 1000:
            raise ValueError(
                f'Line item {i}: sets must be between 1 and 1,000.'
            )
        
        # Validate paper size
        paper_size = item.get('paper_size', 'A4')
        if paper_size not in VALID_PAPER_SIZES:
            raise ValueError(
                f'Line item {i}: invalid paper size "{paper_size}". '
                f'Valid sizes: {", ".join(VALID_PAPER_SIZES)}'
            )
        
        # Validate sides
        sides = item.get('sides', 'SINGLE')
        if sides not in VALID_SIDES:
            raise ValueError(
                f'Line item {i}: invalid sides value "{sides}". '
                f'Valid values: {", ".join(VALID_SIDES)}'
            )


# ── Shared helpers ───────────────────────────────────────────────────────────

def _price_line_items(
    line_items_data: List[Dict], 
    branch
) -> Tuple[List[Dict], Decimal, List[str]]:
    """
    Price a list of raw line item dicts against branch pricing rules.

    Args:
        line_items_data: List of dicts with service, pages, sets, etc.
        branch: Branch instance for pricing rules

    Returns:
        Tuple of (priced_items, total, names)
        - priced_items: List of dicts ready for JobLineItem creation
        - total: Decimal total estimated cost
        - names: List of service names for title generation

    Raises:
        ValueError: If no valid line items could be priced
    """
    from apps.jobs.models import Service
    from apps.jobs.pricing_engine import PricingEngine

    priced_items = []
    total = Decimal('0.00')
    names = []
    errors = []

    for i, item in enumerate(line_items_data):
        try:
            svc = Service.objects.select_related('category').get(
                pk=item['service'],
                is_active=True,
            )
        except Service.DoesNotExist:
            errors.append(f'Service with ID {item.get("service")} not found or inactive.')
            continue

        pg = int(item.get('pages', 1))
        sets = int(item.get('sets', 1))
        is_color = bool(item.get('is_color', False))

        try:
            pricing = PricingEngine.get_price(
                service=svc,
                branch=branch,
                quantity=sets,
                is_color=is_color,
                pages=pg,
            )
            
            if not pricing or 'total' not in pricing:
                errors.append(f'Failed to calculate price for {svc.name}.')
                continue
                
            line_total = Decimal(str(pricing.get('total', 0)))
            unit_price = Decimal(str(pricing.get('base_price', 0)))
            
            # Validate pricing is non-negative
            if line_total < 0 or unit_price < 0:
                errors.append(f'Invalid negative pricing for {svc.name}.')
                continue
                
            total += line_total
            names.append(svc.name)
            
            priced_items.append({
                'service': svc,
                'pages': pg,
                'sets': sets,
                'quantity': sets,
                'is_color': is_color,
                'paper_size': item.get('paper_size', 'A4'),
                'sides': item.get('sides', 'SINGLE'),
                'unit_price': unit_price,
                'line_total': line_total,
                'label': svc.name,
                'position': i,
            })
            
        except (ValueError, TypeError, InvalidOperation) as e:
            errors.append(f'Pricing error for {svc.name}: {str(e)}')
            continue
        except Exception as e:
            logger.exception(f'Unexpected pricing error for service {svc.pk}')
            errors.append(f'Unexpected error pricing {svc.name}.')
            continue

    # Log all pricing errors
    if errors:
        for error in errors:
            logger.warning(f'Line item pricing error: {error}')
        
        # Only fail completely if no items were priced
        if not priced_items:
            raise ValueError(
                f'No valid line items could be priced. Errors: {"; ".join(errors[:3])}'
            )

    return priced_items, total, names


def _build_title(names: List[str]) -> str:
    """
    Build a descriptive job title from service names.
    
    Args:
        names: List of service name strings
        
    Returns:
        Formatted title string (max 200 chars)
    """
    if not names:
        return 'Untitled Job'
    
    if len(names) == 1:
        title = names[0]
    elif len(names) <= 3:
        title = ', '.join(names)
    else:
        title = ', '.join(names[:3]) + f' +{len(names) - 3} more'
    
    # Truncate if too long
    if len(title) > 200:
        title = title[:197] + '...'
    
    return title


def _create_line_items(job, priced_items: List[Dict]) -> None:
    """
    Bulk-create JobLineItem records for a job.
    
    Args:
        job: Job instance
        priced_items: List of priced item dicts
    """
    from apps.jobs.models import JobLineItem
    
    line_items = []
    for item in priced_items:
        line_items.append(JobLineItem(
            job=job,
            service=item['service'],
            quantity=item['quantity'],
            pages=item['pages'],
            sets=item['sets'],
            is_color=item['is_color'],
            paper_size=item['paper_size'],
            sides=item['sides'],
            unit_price=item['unit_price'],
            line_total=item['line_total'],
            label=item.get('label', item['service'].name),
            position=item.get('position', 0),
        ))
    
    if line_items:
        JobLineItem.objects.bulk_create(line_items)
        logger.info(
            f'Created {len(line_items)} line items for job {job.pk}'
        )


# ── Service commands ─────────────────────────────────────────────────────────

@transaction.atomic
def save_draft(user, branch, data: dict) -> Dict[str, Any]:
    """
    Save an in-progress cart as a DRAFT job.

    Args:
        user: CustomUser (the attendant)
        branch: Branch instance
        data: Raw request.data dict with line_items, customer, etc.

    Returns:
        dict: {id, job_number, title, total, expires_at}

    Raises:
        PermissionError: User doesn't belong to this branch
        ValueError: Branch lock, Sunday block, invalid line items, etc.
    """
    from apps.jobs.models import Job
    from apps.finance.sheet_engine import SheetEngine
    from apps.customers.models import CustomerProfile
    from datetime import timedelta

    # Validate user authorization
    _validate_user_branch(user, branch)

    # Check Sunday closure
    today = timezone.localdate()
    if today.weekday() == 6:
        raise ValueError('Branch is closed on Sundays. No jobs can be recorded.')

    # Check branch lock status
    lock = SheetEngine(branch).get_branch_lock_status()
    if not lock['can_create_jobs']:
        raise ValueError(lock['lock_reason'] or 'Job creation is currently locked.')

    # Extract and validate line items
    line_items_data = data.get('line_items', [])
    _validate_line_items(line_items_data)

    # Price line items
    priced_items, total, names = _price_line_items(line_items_data, branch)

    # Get or validate customer
    customer = None
    customer_id = data.get('customer')
    if customer_id:
        try:
            customer = CustomerProfile.objects.select_related('branch').get(
                pk=customer_id,
                is_active=True,
            )
            # Validate customer belongs to this branch or is global
            if customer.branch and customer.branch != branch:
                raise ValueError(
                    f'Customer {customer.name} does not belong to this branch.'
                )
        except CustomerProfile.DoesNotExist:
            raise ValueError(f'Customer with ID {customer_id} not found.')

    # Get or create today's sheet
    sheet_engine = SheetEngine(branch)
    sheet, created = sheet_engine.get_or_open_today(opened_by=user)

    # Set first job opener if sheet was auto-opened
    if created:
        sheet_engine.set_first_job_opener(sheet, user)

    # Create draft job
    now = timezone.now()
    expires = now + timedelta(days=DRAFT_EXPIRY_DAYS)

    job = Job.objects.create(
        branch=branch,
        intake_by=user,
        customer=customer,
        title=_build_title(names),
        job_type='INSTANT',
        status=Job.DRAFT,
        estimated_cost=total,
        daily_sheet=sheet,
        draft_expires_at=expires,
        intake_channel=data.get('intake_channel', 'WALK_IN'),
        is_routed=data.get('is_routed', False),
    )

    # Create line items
    _create_line_items(job, priced_items)

    # Broadcast cache invalidations
    broadcast_invalidation(branch.id, [
        'jobStats', 'recentJobs', 'jobs', 'todaySummary',
        'attendant-stats', 'attendant-my-jobs-recent',
        'attendant-my-jobs', 'notifCount', 'notifications',
    ])

    logger.info(
        f'Draft job {job.job_number} created by {user.full_name} '
        f'with {len(priced_items)} line items, total: {total}'
    )

    return {
        'id': job.id,
        'job_number': job.job_number,
        'title': job.title,
        'total': str(total),
        'expires_at': expires.isoformat(),
        'status': job.status,
        'line_items_count': len(priced_items),
    }


@transaction.atomic
def create_late_job(user, branch, data: dict) -> Any:
    """
    BM creates a post-closing job after branch closing time.

    Args:
        user: CustomUser (must be BRANCH_MANAGER)
        branch: Branch instance
        data: Raw request.data dict

    Returns:
        Job instance

    Raises:
        PermissionError: Not a BM or wrong branch
        ValueError: Branch still open, missing reason, no valid items, etc.
    """
    from apps.jobs.models import Job
    from apps.finance.sheet_engine import SheetEngine
    from apps.hr.shift_engine import ShiftEngine as HRShiftEngine
    from apps.finance.models import CashierFloat
    from apps.customers.models import CustomerProfile

    # Validate user is BM
    role_name = getattr(getattr(user, 'role', None), 'name', '')
    if role_name != 'BRANCH_MANAGER':
        raise PermissionError(
            'Only a Branch Manager can create post-closing jobs.'
        )

    # Validate branch authorization
    _validate_user_branch(user, branch)

    # Check if branch is actually closed
    try:
        bm_schedule = HRShiftEngine(branch).get_role_schedule('BRANCH_MANAGER')
        if bm_schedule.get('can_create_jobs') and not bm_schedule.get('is_post_closing'):
            raise ValueError(
                'Branch is still open. Use the standard New Job flow.'
            )
    except Exception as e:
        logger.warning(f'Failed to check branch schedule: {str(e)}')
        # Allow creation if we can't check schedule (system resilience)

    # Validate post-closing reason
    reason = data.get('post_closing_reason', '').strip()
    if not reason:
        raise ValueError('A reason is required for post-closing jobs.')
    
    if len(reason) > MAX_POST_CLOSING_REASON_LENGTH:
        raise ValueError(
            f'Post-closing reason cannot exceed {MAX_POST_CLOSING_REASON_LENGTH} characters.'
        )

    # Validate line items
    line_items_data = data.get('line_items', [])
    _validate_line_items(line_items_data)

    # Get today's sheet
    sheet_engine = SheetEngine(branch)
    sheet, _ = sheet_engine.get_or_open_today(opened_by=user)
    
    if not sheet:
        raise ValueError('No active sheet for today. Cannot create late job.')

    # Price line items
    priced_items, total, names = _price_line_items(line_items_data, branch)

    # Get customer if provided
    customer = None
    customer_id = data.get('customer')
    if customer_id:
        try:
            customer = CustomerProfile.objects.get(
                pk=customer_id,
                is_active=True,
            )
        except CustomerProfile.DoesNotExist:
            logger.warning(f'Customer {customer_id} not found for late job')

    # Check cashier availability
    today = timezone.localdate()
    cashier_active = CashierFloat.objects.filter(
        daily_sheet__branch=branch,
        daily_sheet__date=today,
        is_signed_off=False,
        morning_acknowledged=True,
    ).exists()

    # Determine job status based on cashier availability
    if cashier_active:
        job_status = Job.PENDING_PAYMENT
        daily_sheet = sheet
    else:
        job_status = Job.INTAKE_HELD
        daily_sheet = None

    # Parse cash tendered safely
    try:
        cash_tendered = Decimal(str(data.get('cash_tendered', '0') or '0'))
        if cash_tendered < 0:
            cash_tendered = Decimal('0')
    except (ValueError, InvalidOperation):
        cash_tendered = Decimal('0')
        logger.warning('Invalid cash_tendered value, defaulting to 0')

    # Create late job
    job = Job.objects.create(
        branch=branch,
        intake_by=user,
        daily_sheet=daily_sheet,
        customer=customer,
        title=_build_title(names),
        job_type='INSTANT',
        status=job_status,
        estimated_cost=total,
        post_closing=True,
        post_closing_reason=reason,
        post_closing_approved_by=user,
        intake_channel=data.get('intake_channel', 'WALK_IN'),
        cash_tendered=cash_tendered,
        is_routed=data.get('is_routed', False),
    )

    # Create line items
    _create_line_items(job, priced_items)

    # Broadcast cache invalidations
    broadcast_invalidation(branch.id, [
        'paymentQueue', 'jobStats', 'recentJobs',
        'jobs', 'todaySummary', 'attendant-stats',
        'attendant-my-jobs-recent', 'attendant-my-jobs',
        'notifCount', 'notifications',
    ])

    logger.info(
        f'Late job {job.job_number} created by BM {user.full_name} '
        f'with status {job_status}, reason: {reason[:50]}...'
    )

    return job


# ── Service creation ─────────────────────────────────────────────────────────

@transaction.atomic
def create_service(
    user, 
    branch, 
    validated_data: dict, 
    raw_mappings_json: Optional[str] = None
) -> Any:
    """
    Create a new Service with pricing rule and optional consumable mappings.

    Args:
        user: CustomUser creating the service
        branch: Branch instance (or None for global services)
        validated_data: dict from ServiceCreateSerializer.validated_data
        raw_mappings_json: Optional raw JSON string from multipart request.data

    Returns:
        Service instance

    Raises:
        PermissionError: User not authorized to create services
        ValueError: Invalid data or mappings
    """
    from apps.jobs.models import Service, PricingRule
    from apps.inventory.models import ConsumableItem, ServiceConsumable

    # Validate user
    if not user or not user.is_active:
        raise ValueError('User account is not active.')

    # Validate required fields
    d = validated_data
    required_fields = ['name', 'code', 'category', 'unit', 'base_price']
    for field in required_fields:
        if field not in d:
            raise ValueError(f'Missing required field: {field}')

    # Validate service name uniqueness per branch (or globally)
    existing = Service.objects.filter(
        name__iexact=d['name'],
        is_active=True,
    )
    if existing.exists():
        raise ValueError(f'Service with name "{d["name"]}" already exists.')

    # Validate code uniqueness
    if Service.objects.filter(code__iexact=d['code'], is_active=True).exists():
        raise ValueError(f'Service code "{d["code"]}" is already in use.')

    # Validate base price
    try:
        base_price = Decimal(str(d['base_price']))
        if base_price < 0:
            raise ValueError('Base price cannot be negative.')
    except (ValueError, InvalidOperation):
        raise ValueError('Invalid base price value.')

    sides = d.get('sides', 'SINGLE')
    if sides not in VALID_SIDES:
        raise ValueError(f'Invalid sides value: {sides}')

    # Create smart defaults
    name_lower = d['name'].lower()
    smart_defaults = {
        'sides'     : sides,
        'pages'     : 1,
        'sets'      : 1,
        'paper_size': d.get('paper_size', 'A4'),
        'is_color'  : 'color' in name_lower or 'colour' in name_lower,
    }

    # Create service
    service = Service.objects.create(
        name=d['name'][:MAX_SERVICE_NAME_LENGTH],
        code=d['code'],
        category=d['category'],
        unit=d['unit'],
        description=d.get('description', ''),
        image=d.get('image'),
        is_active=True,
        smart_defaults=smart_defaults,
    )

    # Create branch-specific pricing rule if branch provided
    if branch:
        # Validate branch
        if hasattr(user, 'branch') and user.branch_id and user.branch_id != branch.id:
            logger.warning(
                f'User {user.full_name} creating service for different branch {branch.name}'
            )
        
        PricingRule.objects.create(
            service          = service,
            branch           = branch,
            base_price       = base_price,
            color_multiplier = d.get('color_multiplier', Decimal('1.00')),
            is_active        = True,
        )

    # Parse and validate consumable mappings
    mappings_data = []
    if raw_mappings_json and isinstance(raw_mappings_json, str):
        try:
            mappings_data = json.loads(raw_mappings_json)
        except json.JSONDecodeError as e:
            logger.warning(f'Invalid JSON in consumable mappings: {str(e)}')
            raise ValueError(f'Invalid consumable mappings JSON: {str(e)}')

    # Validate mappings array
    if mappings_data:
        if not isinstance(mappings_data, list):
            raise ValueError('Consumable mappings must be a JSON array.')
        
        if len(mappings_data) > 20:  # Limit mappings per service
            raise ValueError('Too many consumable mappings. Maximum 20 allowed.')

    # Create consumable mappings
    if mappings_data:
        for i, mapping in enumerate(mappings_data):
            if not isinstance(mapping, dict):
                logger.warning(f'Invalid mapping at index {i}: not a dict')
                continue
                
            consumable_id = mapping.get('consumable_id')
            if not consumable_id:
                logger.warning(f'Mapping at index {i} missing consumable_id')
                continue

            try:
                consumable = ConsumableItem.objects.select_related('category').get(
                    pk=consumable_id,
                    is_active=True,
                )
                
                # Validate quantity
                try:
                    quantity = Decimal(str(mapping.get('quantity_per_unit', 0)))
                    if quantity <= 0:
                        raise ValueError('Quantity must be positive')
                except (ValueError, InvalidOperation):
                    logger.warning(f'Invalid quantity in mapping {i}, skipping')
                    continue

                # Create or update mapping
                ServiceConsumable.objects.update_or_create(
                    service=service,
                    consumable=consumable,
                    defaults={
                        'quantity_per_unit': quantity,
                        'applies_to_color': mapping.get('applies_to_color', True),
                        'applies_to_bw': mapping.get('applies_to_bw', True),
                    }
                )
                logger.info(
                    f'Created consumable mapping: {service.name} -> '
                    f'{consumable.name} ({quantity} per unit)'
                )
                
            except ConsumableItem.DoesNotExist:
                logger.warning(
                    f'Consumable with ID {consumable_id} not found, skipping'
                )
            except Exception as e:
                logger.error(
                    f'Error creating consumable mapping for {consumable_id}: {str(e)}'
                )

    # Auto-map toner based on paper selection
    try:
        _auto_map_toner(service, mappings_data, sides=sides)
    except Exception as e:
        logger.error(f'Auto toner mapping failed for service {service.name}: {str(e)}')
        # Non-critical, continue without auto-mapping

    logger.info(
        f'Service "{service.name}" created by {user.full_name} '
        f'with {len(mappings_data)} manual mappings'
    )

    return service


def _auto_map_toner(
    service, 
    manual_mappings: List[Dict], 
    sides: str = 'SINGLE'
) -> None:
    """
    Auto-create toner ServiceConsumable mappings based on paper selection.

    Rules:
      - A5 paper → 0.005 toner per page
      - A4 paper → 0.01 toner per page  
      - A3 paper → 0.02 toner per page
      - Color services → all 4 toners (CMYK)
      - B&W services → black toner only
      - Ambiguous name → both color and B&W toners

    Args:
        service: Service instance
        manual_mappings: List of manual mapping dicts (to detect paper selections)
        sides: 'SINGLE' or 'DOUBLE' (doubles toner for double-sided)
    """
    from apps.inventory.models import ConsumableItem, ServiceConsumable

    # Extract paper consumable IDs from manual mappings
    selected_ids = [m.get('consumable_id') for m in (manual_mappings or []) 
                    if m.get('consumable_id')]
    
    if not selected_ids:
        return

    # Find paper consumables that were selected
    paper_consumables = ConsumableItem.objects.filter(
        id__in=selected_ids,
        category__name__icontains='Paper',
        is_active=True,
    ).exclude(unit_type='PERCENT')

    if not paper_consumables.exists():
        return

    # Toner consumption rates by paper size
    TONER_RATES = {
        'A5': Decimal('0.005'),
        'A4': Decimal('0.01'),
        'A3': Decimal('0.02'),
        'A2': Decimal('0.04'),
        'LETTER': Decimal('0.01'),  # Similar to A4
        'LEGAL': Decimal('0.012'),
    }

    # Determine color requirements from service name
    name_lower = service.name.lower()
    is_color_name = 'color' in name_lower or 'colour' in name_lower
    is_bw_name = 'b&w' in name_lower or 'bw' in name_lower or 'black' in name_lower

    # Determine toner applicability
    if is_color_name and not is_bw_name:
        applies_color, applies_bw = True, False
    elif is_bw_name and not is_color_name:
        applies_color, applies_bw = False, True
    else:
        # Ambiguous - apply both
        applies_color, applies_bw = True, True

    # Find toner consumables
    toner_black = ConsumableItem.objects.filter(
        name__icontains='Toner Black',
        is_active=True,
    ).first()
    
    toner_cyan = ConsumableItem.objects.filter(
        name__icontains='Toner Cyan',
        is_active=True,
    ).first()
    
    toner_magenta = ConsumableItem.objects.filter(
        name__icontains='Toner Magenta',
        is_active=True,
    ).first()
    
    toner_yellow = ConsumableItem.objects.filter(
        name__icontains='Toner Yellow',
        is_active=True,
    ).first()

    # Create toner mappings for each paper selection
    mappings_created = 0
    for paper in paper_consumables:
        paper_size = getattr(paper, 'paper_size', 'A4')
        rate = TONER_RATES.get(paper_size, Decimal('0.01'))
        
        # Double the rate for double-sided
        if sides == 'DOUBLE':
            rate = rate * 2

        # Determine which toners to map
        toners = []
        if applies_bw and toner_black:
            toners.append(toner_black)
        
        if applies_color:
            for toner, name in [
                (toner_cyan, 'Cyan'),
                (toner_magenta, 'Magenta'), 
                (toner_yellow, 'Yellow')
            ]:
                if toner:
                    toners.append(toner)

        # Create mappings
        for toner in toners:
            try:
                # Check if mapping already exists
                existing = ServiceConsumable.objects.filter(
                    service=service,
                    consumable=toner,
                ).exists()
                
                if not existing:
                    ServiceConsumable.objects.create(
                        service=service,
                        consumable=toner,
                        quantity_per_unit=rate,
                        applies_to_color=applies_color,
                        applies_to_bw=applies_bw,
                    )
                    mappings_created += 1
                    
            except Exception as e:
                logger.error(
                    f'Failed to create toner mapping for {toner.name}: {str(e)}'
                )

    if mappings_created > 0:
        logger.info(
            f'Auto-created {mappings_created} toner mappings for service {service.name}'
        )