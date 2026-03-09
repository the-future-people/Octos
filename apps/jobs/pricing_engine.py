from decimal import Decimal
from apps.jobs.models.pricing import PricingRule


class PricingEngine:
    """
    Calculates the cost of a job based on its specifications.
    Always checks for branch-specific pricing first,
    then falls back to company-wide default.
    System truth — no manual price entry by attendants.
    """

    def __init__(self, service, branch):
        self.service = service
        self.branch = branch
        self.rule = self._get_rule()

    def _get_rule(self):
        """
        Get the most specific pricing rule available.
        Branch-specific → Company-wide default.
        """
        # Try branch-specific first
        rule = PricingRule.objects.filter(
            service=self.service,
            branch=self.branch,
            is_active=True
        ).first()

        # Fall back to company-wide default
        if not rule:
            rule = PricingRule.objects.filter(
                service=self.service,
                branch__isnull=True,
                is_active=True
            ).first()

        return rule

    def calculate(self, quantity=1, is_color=False, pages=1):
        """
        Calculate the total cost for a job.

        Args:
            quantity: Number of copies or pieces
            is_color: Whether the job is color (applies color_multiplier)
            pages: Number of pages (for per-page services)

        Returns:
            dict with breakdown and total
        """
        if not self.rule:
            return {
                'success': False,
                'error': f'No pricing rule found for {self.service.name} at {self.branch.name}',
                'total': Decimal('0.00')
            }

        base = self.rule.base_price
        multiplier = self.rule.color_multiplier if is_color else Decimal('1.00')
        unit = self.service.unit

        if unit == 'PER_PAGE':
            subtotal = base * multiplier * pages * quantity
        elif unit == 'PER_COPY':
            subtotal = base * multiplier * quantity
        elif unit == 'PER_PIECE':
            subtotal = base * multiplier * quantity
        elif unit == 'PER_SQM':
            subtotal = base * multiplier * quantity
        elif unit == 'PER_SET':
            subtotal = base * multiplier * quantity
        elif unit == 'FLAT_RATE':
            subtotal = base * multiplier
        else:
            subtotal = base * multiplier * quantity

        total = subtotal.quantize(Decimal('0.01'))

        return {
            'success': True,
            'service': self.service.name,
            'branch': self.branch.name,
            'unit': self.service.get_unit_display(),
            'base_price': base,
            'color_multiplier': multiplier,
            'quantity': quantity,
            'pages': pages,
            'is_color': is_color,
            'total': total,
            'pricing_source': 'branch' if self.rule.branch else 'company_default'
        }

    @classmethod
    def get_price(cls, service, branch, quantity=1, is_color=False, pages=1):
        """
        Convenience class method for quick price lookups.
        """
        engine = cls(service, branch)
        return engine.calculate(quantity, is_color, pages)