"""
What a customer saved on a job or a proforma (17 Nov 2026): the bulk price
and a price lowered by hand, the same words on every receipt and proforma.
"""
from decimal import Decimal

CENT = Decimal('0.01')


def savings(target):
    """
    {'list', 'bulk', 'discount', 'reason', 'total', 'saved'} as strings, or
    None when nothing was saved. target is a Job or a ProformaInvoice.
    """
    if target is None:
        return None
    bulk = Decimal(str(getattr(target, 'bulk_saving', 0) or 0))
    discount = Decimal(str(getattr(target, 'discount_amount', 0) or 0))
    if bulk <= 0 and discount <= 0:
        return None
    total = Decimal(str((getattr(target, 'estimated_cost', None) if hasattr(target, 'job_number')
                         else getattr(target, 'total', None)) or 0))
    listed = total + bulk + discount
    return {
        'list': f'{listed.quantize(CENT):,.2f}',
        'bulk': f'{bulk.quantize(CENT):,.2f}' if bulk > 0 else None,
        'discount': f'{discount.quantize(CENT):,.2f}' if discount > 0 else None,
        'reason': getattr(target, 'discount_reason', '') or '',
        'total': f'{total.quantize(CENT):,.2f}',
        'saved': f'{(bulk + discount).quantize(CENT):,.2f}',
    }
