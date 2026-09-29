from decimal import Decimal
from apps.jobs.models import PricingRule


# Units whose quantity is an area rather than a count.
AREA_UNITS = ('SQFT', 'SQCM', 'SQM')

def square_feet(width_in, height_in) -> Decimal:
    """
    (width" × height") ÷ 144 — the area basis every large-format job is
    priced on. Dimensions are taken in inches because that is what the
    customer gives and what the machine cuts.

    The area is not rounded. Only the money is, at the end.
    """
    return (
        Decimal(str(width_in)) * Decimal(str(height_in))
    ) / Decimal('144')

def quote_line(service, branch, specifications=None, quantity=1) -> dict:
    """
    Price one line of a job from its filled-in specification.

    The single quote path. The counter, the storefront and any future
    assessment all call this, so a banner costs the same wherever it is
    quoted — and the arithmetic that turns inches into an area lives in
    one place rather than in whoever happens to be calling.

    specifications is the same free-form dict the line item carries, so
    an area service is refused outright when its dimensions are absent.
    Pricing a missing width as zero area is how a banner gets sold for
    nothing.
    """
    specs     = specifications or {}
    unit_norm = (service.unit or '').upper().replace('PER_', '')
    quantity  = int(quantity or 1)

    if unit_norm in AREA_UNITS:
        width  = specs.get('width_in')
        height = specs.get('height_in')
        if not width or not height:
            return {
                'success': False,
                'error': (
                    f'{service.name} is priced by area and needs a width '
                    f'and a height in inches.'
                ),
                'total': Decimal('0.00'),
            }
        area   = square_feet(width, height)
        result = PricingEngine.get_price(
            service=service, branch=branch,
            quantity=area, pages=quantity,
        )
        if not result['success']:
            return result

        total      = result['total']
        unit_price = (total / Decimal(str(quantity))).quantize(Decimal('0.01'))
        floor      = PricingEngine(service, branch).rule.minimum_price or Decimal('0')
        result.update({
            'area_sqft'      : area,
            'unit_price'     : unit_price,
            'minimum_applied': bool(floor and unit_price <= floor),
        })
        return result

    pages  = int(specs.get('pages') or 1)
    result = PricingEngine.get_price(
        service=service, branch=branch,
        quantity=quantity, pages=pages,
        is_color=bool(specs.get('is_color')),
    )
    if result['success']:
        result.setdefault('area_sqft', None)
        result.setdefault(
            'unit_price',
            (result['total'] / Decimal(str(quantity))).quantize(Decimal('0.01')),
        )
        result.setdefault('minimum_applied', False)
    return result
    """
    (width" × height") ÷ 144 — the area basis every large-format job is
    priced on. Dimensions are taken in inches because that is what the
    customer gives and what the machine cuts.

    The area is not rounded. Only the money is, at the end.
    """
    return (
        Decimal(str(width_in)) * Decimal(str(height_in))
    ) / Decimal('144')


class PricingEngine:
    """
    Calculates the cost of a job based on its specifications.
    Always checks for branch-specific pricing first,
    then falls back to company-wide default.
    System truth — no manual price entry by attendants.

    Supports three pricing modes:
    1. Standard   — base_price × quantity (× color_multiplier if color)
    2. Per-unit tiers — price_per_unit varies by quantity band (Typing)
    3. Flat-fee tiers — fixed price per quantity band (Binding)

    Tier format:
    Per-unit: [{"min": 1, "max": 5, "price_per_unit": 20.00}, ...]
    Flat-fee:  [{"min": 1, "max": 100, "flat_price": 10.00}, ...]
    max: null means no upper bound.
    """

    def __init__(self, service, branch) -> None:
        self.service = service
        self.branch  = branch
        self.rule    = self._get_rule()

    def _get_rule(self):
        """
        Get the most specific pricing rule available.
        Branch-specific → Company-wide default.
        Cached 5 minutes per service+branch pair.
        """
        from django.core.cache import cache
        cache_key = f'pricing_rule:{self.service.pk}:{self.branch.pk}'
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        rule = PricingRule.objects.filter(
            service  = self.service,
            branch   = self.branch,
            is_active= True,
        ).first()

        if not rule:
            rule = PricingRule.objects.filter(
                service        = self.service,
                branch__isnull = True,
                is_active      = True,
            ).first()

        if rule is not None:
            cache.set(cache_key, rule, 300)
        return rule

    def calculate(self, quantity: int = 1, is_color: bool = False, pages: int = 1,
                  condition_params: dict = None):
        """
        Calculate the total cost for a job.

        Args:
            quantity : Number of copies, pieces, or pages depending on service
            is_color : Whether the job is color (applies color_multiplier)
            pages    : Number of pages (for per-page services)

        Returns:
            dict with breakdown and total
        """
        if not self.rule:
            return {
                'success' : False,
                'error'   : (
                    f"No pricing rule found for {self.service.name} "
                    f"at {self.branch.name}"
                ),
                'total'   : Decimal('0.00'),
            }

       # ── Tiered pricing takes priority ─────────────────────
        if self.rule.pricing_tiers:
            return self._calculate_tiered(quantity, pages, condition_params or {})

        # ── Standard pricing ──────────────────────────────────
        base       = self.rule.base_price
        multiplier = self.rule.color_multiplier if is_color else Decimal('1.00')
        unit       = self.service.unit

        # Normalise unit — handle both legacy lowercase and PER_ prefixed formats
        unit_norm = unit.upper().replace('PER_', '')

        if unit_norm in ('COPY', 'PIECE', 'PAGE', 'SHEET'):
            # Per-copy/piece services: base × pages × sets × color
            subtotal = base * multiplier * Decimal(str(pages)) * Decimal(str(quantity))
        elif unit_norm in ('SQFT', 'SQCM', 'SQM'):
            # Area-based: quantity is the area of one piece, pages is how
            # many of them. Ignoring pages here priced four banners as one.
            subtotal = (
                base * multiplier
                * Decimal(str(quantity))
                * Decimal(str(pages))
            )
        elif unit_norm == 'JOB':
            # Flat per job — no quantity multiplication
            subtotal = base * multiplier
        else:
            subtotal = base * multiplier * Decimal(str(pages)) * Decimal(str(quantity))

        # A floor under one piece, applied before quantity: a small
        # banner costs the same in file prep, cutting and packing as a
        # large one, so three small pieces are three minimums.
        floor = self.rule.minimum_price or Decimal('0')
        if floor > 0:
            pieces    = Decimal(str(pages)) if pages else Decimal('1')
            per_piece = subtotal / pieces
            if per_piece < floor:
                subtotal = floor * pieces

        total = subtotal.quantize(Decimal('0.01'))

        return {
            'success'        : True,
            'service'        : self.service.name,
            'branch'         : self.branch.name,
            'unit'           : self.service.unit,
            'base_price'     : str(base),
            'color_multiplier': str(multiplier),
            'quantity'       : quantity,
            'pages'          : pages,
            'is_color'       : is_color,
            'total'          : total,
            'pricing_mode'   : 'standard',
            'pricing_source' : 'branch' if self.rule.branch else 'company_default',
        }

    def _calculate_tiered(self, quantity: int, pages: int, condition_params: dict = None):
        """
        Calculate price using pricing_tiers on the rule.
        Supports two tier modes:
        1. Quantity range tiers — matched by min/max
        2. Conditional tiers   — matched by condition + value/range
        """
        tiers             = self.rule.pricing_tiers
        unit              = self.service.unit
        condition_params  = condition_params or {}

        # Check if tiers are conditional (have a 'condition' key)
        if tiers and 'condition' in tiers[0]:
            tier = self._find_conditional_tier(tiers, condition_params)
        else:
            qty  = pages if pages > 1 else quantity
            tier = self._find_tier(tiers, qty)

        if tier is None:
            return {
                'success' : False,
                'error'   : (
                    f"No matching price tier for quantity {quantity} "
                    f"on {self.service.name}"
                ),
                'total'   : Decimal('0.00'),
            }

        if 'flat_price' in tier:
            # Flat fee × pages × copies
            subtotal = (
                Decimal(str(tier['flat_price']))
                * Decimal(str(pages))
                * Decimal(str(quantity))
            )
            mode = 'flat_tier'
        else:
            # Per-unit tier — price_per_unit × pages × copies
            subtotal = (
                Decimal(str(tier['price_per_unit']))
                * Decimal(str(pages))
                * Decimal(str(quantity))
            )
            mode = 'per_unit_tier'

        total = subtotal.quantize(Decimal('0.01'))

        return {
            'success'        : True,
            'service'        : self.service.name,
            'branch'         : self.branch.name,
            'unit'           : unit,
            'quantity'       : quantity,
            'pages'          : pages,
            'tier_applied'   : tier,
            'total'          : total,
            'pricing_mode'   : mode,
            'pricing_source' : 'branch' if self.rule.branch else 'company_default',
        }

    @staticmethod
    def _find_tier(tiers: list, qty: int) -> dict | None:
        """
        Find the matching tier for a given quantity.
        max: null means no upper bound.
        """
        for tier in tiers:
            min_val = tier.get('min', 0)
            max_val = tier.get('max')
            if max_val is None:
                if qty >= min_val:
                    return tier
            else:
                if min_val <= qty <= max_val:
                    return tier
        return None

    @staticmethod
    def _find_conditional_tier(tiers: list, condition_params: dict) -> dict | None:
        """
        Find a matching tier based on a condition field and value.

        Supports two conditional formats:
        1. Exact value match:
           {"condition": "output_mode", "value": "DIGITAL", "flat_price": 20.00}

        2. Range match on a numeric param:
           {"condition": "ring_size", "min": 6, "max": 24, "flat_price": 10.00}
        """
        for tier in tiers:
            condition = tier.get('condition')
            if not condition:
                continue

            param_value = condition_params.get(condition)
            if param_value is None:
                continue

            # Exact value match
            if 'value' in tier:
                if str(param_value) == str(tier['value']):
                    return tier

            # Numeric range match
            elif 'min' in tier:
                try:
                    num_val = int(param_value)
                    min_val = tier.get('min', 0)
                    max_val = tier.get('max')
                    if max_val is None:
                        if num_val >= min_val:
                            return tier
                    else:
                        if min_val <= num_val <= max_val:
                            return tier
                except (ValueError, TypeError):
                    continue

        return None

    @classmethod
    def get_price(cls, service, branch, quantity: int = 1,
                  is_color: bool = False, pages: int = 1,
                  condition_params: dict = None):
        """Convenience class method for quick price lookups."""
        return cls(service, branch).calculate(quantity, is_color, pages, condition_params)