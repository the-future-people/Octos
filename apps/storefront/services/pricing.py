"""
Pricing a whole online order: one rule, used by the storefront and by
Octos on WhatsApp.

Moved out of the storefront's OrderDetailView._price (Nov 2026), which
now passes straight through to price_lines, so every existing caller is
unchanged and Octos prices an order exactly as the storefront does.
"""
import uuid
from decimal import Decimal


def price_lines(raw_lines, existing_ids=None):
    """
    Quote every line again, through the same function the counter
    uses. Whatever price the browser sent is ignored.

    Returns (priced lines, total, None), or (None, None, why not).
    """
    from apps.jobs.models import Service
    from apps.jobs.pricing_engine import quote_line
    from apps.jobs.services.availability import can_make, price_addons

    if not isinstance(raw_lines, list):
        return None, None, 'line_items must be a list.'

    priced = []
    total = Decimal('0.00')
    existing_ids = existing_ids or {}

    for line in raw_lines:
        try:
            service = Service.objects.get(pk=line.get('service'), is_active=True)
        except (Service.DoesNotExist, ValueError, TypeError):
            return None, None, f"Service {line.get('service')} is not available."

        quantity = int(line.get('quantity') or 1)
        specs = line.get('specifications') or {}

        if not can_make(service):
            return None, None, f'{service.name} is coming soon.'

        quote = quote_line(
            service=service, branch=None,
            specifications=specs, quantity=quantity,
        )
        if not quote.get('success'):
            return None, None, quote.get('error', 'This line could not be priced.')

        addons, addons_total, problem = price_addons(
            service, line.get('addons') or [], quantity, specs,
        )
        if problem:
            return None, None, problem

        priced.append({
            # An identity that survives repricing. Position in a
            # list is not one: removing the first line would hand
            # its artwork to the second.
            # Keep the identity the caller sent, or the one this
            # service already had on the order. Minting a fresh id
            # on every reprice would orphan the line's artwork:
            # resizing a banner would quietly destroy the file.
            'id': (
                line.get('id')
                or existing_ids.get(service.id)
                or uuid.uuid4().hex[:12]
            ),
            'service': service.id,
            # What the customer ordered, in their words: the product
            # and its side. base_name is the service's own, which
            # photos are found by.
            'service_name': (
                f'{service.display_name} · {service.variant_label}'
                if service.display_name and service.variant_label
                else (service.display_name or service.name)
            ),
            'base_name': service.name,
            'quantity': quantity,
            'specifications': specs,
            'unit_price': str(quote.get('unit_price') or quote['total']),
            'base_total': str(quote['total']),
            'addons': addons,
            'total': str(Decimal(str(quote['total'])) + addons_total),
        })
        total += Decimal(str(quote['total'])) + addons_total

    return priced, total, None