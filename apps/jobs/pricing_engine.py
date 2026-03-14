from decimal import Decimal
from apps.jobs.models.pricing import PricingRule


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
        """
        rule = PricingRule.objects.filter(
            service  = self.service,
            branch   = self.branch,
            is_active= True,
        ).first()

        if not rule:
            rule = PricingRule.objects.filter(
                service      = self.service,
                branch__isnull = True,
                is_active    = True,
            ).first()

        return rule

    def calculate(self, quantity: int = 1, is_color: bool = False, pages: int = 1):
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
            return self._calculate_tiered(quantity, pages)

        # ── Standard pricing ──────────────────────────────────
        base       = self.rule.base_price
        multiplier = self.rule.color_multiplier if is_color else Decimal('1.00')
        unit       = self.service.unit

        if unit == 'page':
            subtotal = base * multiplier * Decimal(str(pages)) * Decimal(str(quantity))
        elif unit in ('piece', 'sheet'):
            subtotal = base * multiplier * Decimal(str(quantity))
        elif unit == 'sqm':
            subtotal = base * multiplier * Decimal(str(quantity))
        elif unit == 'set':
            subtotal = base * multiplier * Decimal(str(quantity))
        elif unit == 'flat':
            subtotal = base * multiplier
        else:
            subtotal = base * multiplier * Decimal(str(quantity))

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

    def _calculate_tiered(self, quantity: int, pages: int):
        """
        Calculate price using pricing_tiers on the rule.
        Determines whether to use per-unit or flat-fee logic
        based on the keys present in the first tier.
        """
        tiers = self.rule.pricing_tiers
        unit  = self.service.unit

        # If pages > 1 was explicitly passed, the tier is driven by page count.
        # This covers both page-unit services (Typing) and piece-unit services
        # tiered by pages (Binding). Otherwise fall back to quantity.
        qty  = pages if pages > 1 else quantity
        tier = self._find_tier(tiers, qty)

        if tier is None:
            return {
                'success' : False,
                'error'   : (
                    f"No matching price tier for quantity {qty} "
                    f"on {self.service.name}"
                ),
                'total'   : Decimal('0.00'),
            }

        if 'flat_price' in tier:
            # Flat fee — fixed price regardless of exact quantity
            # Multiply by number of copies (quantity) for multi-copy binding jobs
            subtotal = Decimal(str(tier['flat_price'])) * Decimal(str(quantity))
            mode     = 'flat_tier'
        else:
            # Per-unit tier — price_per_unit × qty × copies
            subtotal = (
                Decimal(str(tier['price_per_unit']))
                * Decimal(str(qty))
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

    @classmethod
    def get_price(cls, service, branch, quantity: int = 1,
                  is_color: bool = False, pages: int = 1):
        """Convenience class method for quick price lookups."""
        return cls(service, branch).calculate(quantity, is_color, pages)