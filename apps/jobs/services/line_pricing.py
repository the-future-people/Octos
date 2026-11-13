"""
Pricing a job's line when it is saved (13 Nov 2026).

Saving a job priced every line with PricingEngine.get_price(quantity=count).
Right for copies and flyers; wrong for anything priced by area: 300 stickers
of 4 x 2 inches at GHS 2.80 a square foot became 300 x 2.80 = GHS 840.00
instead of 16.67 sq ft x 2.80 = GHS 46.67, while the preview (quote_line)
showed the right price.

Area-priced services now go through quote_line, the one quote path, so the
price saved is the price shown. Every other service keeps its existing path.
"""
from decimal import Decimal

from apps.jobs.pricing_engine import AREA_UNITS, quote_line


def is_area(service):
    """Priced by area (per square foot or metre)."""
    return (getattr(service, 'unit', '') or '').upper().replace('PER_', '') in AREA_UNITS


def area_specs(item):
    """The size, wherever the item carries it: in specifications, or beside them."""
    specs = dict(item.get('specifications') or {})
    for key in ('width_in', 'height_in'):
        if not specs.get(key) and item.get(key):
            specs[key] = item[key]
    return specs


def price_area_line(service, branch, item, count):
    """
    The line's price through quote_line, in the shape the save paths read:
    total, and base_price as the price of one piece (not the rate).
    """
    quote = quote_line(service, branch, area_specs(item), int(count or 1))
    if not quote.get('success'):
        return {'success': False, 'total': Decimal('0.00'),
                'error': quote.get('error') or f'Could not price {service.name}.'}
    return {
        'success': True,
        'total': quote['total'],
        'base_price': quote.get('unit_price'),
        'area_sqft': quote.get('area_sqft'),
        'minimum_applied': quote.get('minimum_applied', False),
    }
