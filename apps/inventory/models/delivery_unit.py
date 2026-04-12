from django.db import models
from apps.core.models import AuditModel


class DeliveryUnit(AuditModel):
    """
    Defines how a consumable is physically packaged for delivery.

    Stock is tracked in base units (sheets, pcs, %) but delivery
    happens in packs (boxes, reams, cartridges). This model bridges
    the two — enabling the replenishment engine to calculate how many
    whole packs to order and display delivery quantities correctly.

    Examples:
      A4 Paper 80gsm   → pack_size=2500, pack_label='box'
      Binding Rings    → pack_size=100,  pack_label='box'
      Toner cartridge  → pack_size=1,    pack_label='cartridge'
      Passport Film    → pack_size=108,  pack_label='box'
    """

    consumable = models.OneToOneField(
        'inventory.ConsumableItem',
        on_delete    = models.CASCADE,
        related_name = 'delivery_unit',
    )
    pack_size = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        help_text      = 'Number of stock units per deliverable pack.',
    )
    pack_label = models.CharField(
        max_length = 50,
        help_text  = 'Human-readable pack name e.g. box, ream, cartridge, unit.',
    )
    notes = models.TextField(
        blank     = True,
        help_text = 'Optional description e.g. "1 box = 2,500 sheets (5 reams)"',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering            = ['consumable__category', 'consumable__name']
        verbose_name        = 'Delivery Unit'
        verbose_name_plural = 'Delivery Units'

    def __str__(self):
        return (
            f"{self.consumable.name} — "
            f"{self.pack_size} {self.consumable.unit_label} / {self.pack_label}"
        )

    @property
    def pack_description(self):
        return (
            f"1 {self.pack_label} = "
            f"{self.pack_size} {self.consumable.unit_label}"
        )