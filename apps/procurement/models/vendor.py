# apps/procurement/models/vendor.py

from django.db import models
from apps.core.models import AuditModel


class Vendor(AuditModel):
    """
    A supplier Farhat purchases from.
    Each vendor has a pricelist of items they supply.
    """

    class PaymentTerm(models.TextChoices):
        CASH          = 'CASH',          'Cash'
        CHEQUE        = 'CHEQUE',        'Cheque'
        MOMO          = 'MOMO',          'Mobile Money'
        BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'

    name         = models.CharField(max_length=200, unique=True)
    contact      = models.CharField(max_length=200, blank=True)
    phone        = models.CharField(max_length=30,  blank=True)
    email        = models.EmailField(blank=True)
    address      = models.TextField(blank=True)
    payment_term = models.CharField(
        max_length = 20,
        choices    = PaymentTerm.choices,
        default    = PaymentTerm.CASH,
    )
    is_active    = models.BooleanField(default=True)
    notes        = models.TextField(blank=True)

    class Meta:
        ordering            = ['name']
        verbose_name        = 'Vendor'
        verbose_name_plural = 'Vendors'

    def __str__(self):
        return self.name


class VendorItem(AuditModel):
    """
    A consumable item supplied by a specific vendor at a known price.
    Price history is maintained for audit and auto-adjustment.
    """

    vendor     = models.ForeignKey(
        Vendor,
        on_delete    = models.CASCADE,
        related_name = 'items',
    )
    consumable = models.ForeignKey(
        'inventory.ConsumableItem',
        on_delete    = models.PROTECT,
        related_name = 'vendor_items',
    )
    current_price = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        help_text      = 'Current unit price from latest verified invoice.',
    )
    price_history = models.JSONField(
        default  = list,
        blank    = True,
        help_text= 'List of {date, price, reference} dicts — oldest first.',
    )
    is_preferred  = models.BooleanField(
        default  = False,
        help_text= 'Preferred vendor for this consumable.',
    )
    variance_threshold = models.DecimalField(
        max_digits     = 5,
        decimal_places = 2,
        default        = 10,
        help_text      = 'Alert Finance if new price deviates by more than this % from current.',
    )
    is_active = models.BooleanField(default=True)
    notes     = models.TextField(blank=True)

    class Meta:
        ordering        = ['vendor__name', 'consumable__name']
        unique_together = [['vendor', 'consumable']]
        verbose_name        = 'Vendor Item'
        verbose_name_plural = 'Vendor Items'

    def __str__(self):
        return f"{self.vendor.name} — {self.consumable.name} @ GHS {self.current_price}"

    def update_price(self, new_price, reference: str = '') -> bool:
        """
        Update current price and append old price to history.
        Returns True if variance threshold was exceeded (Finance alert needed).
        """
        from decimal import Decimal
        from django.utils import timezone

        old_price   = self.current_price
        new_price   = Decimal(str(new_price))
        variance_pct = abs((new_price - old_price) / old_price * 100) if old_price else Decimal('0')

        # Append old price to history
        history = self.price_history or []
        history.append({
            'date'     : timezone.now().date().isoformat(),
            'price'    : str(old_price),
            'reference': reference,
        })
        self.price_history  = history
        self.current_price  = new_price
        self.save(update_fields=['current_price', 'price_history', 'updated_at'])

        return variance_pct > self.variance_threshold