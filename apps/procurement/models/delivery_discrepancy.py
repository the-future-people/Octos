from django.db import models
from django.db import models
from apps.core.models import AuditModel


class DeliveryDiscrepancy(AuditModel):
    """
    Immutable record created when BM accepts delivery with quantity differences.

    Flagged to Operations and RM for resolution.
    Cannot be edited after creation — discrepancies are permanent audit records.
    """

    class Resolution(models.TextChoices):
        PENDING    = 'PENDING',    'Pending Investigation'
        RESOLVED   = 'RESOLVED',  'Resolved'
        WRITTEN_OFF = 'WRITTEN_OFF', 'Written Off'

    order = models.ForeignKey(
        'procurement.ReplenishmentOrder',
        on_delete    = models.PROTECT,
        related_name = 'discrepancies',
    )
    line_item = models.ForeignKey(
        'procurement.ReplenishmentLineItem',
        on_delete    = models.PROTECT,
        related_name = 'discrepancies',
    )
    delivered_qty = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        help_text      = 'What Operations claimed to deliver.',
    )
    accepted_qty = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        help_text      = 'What BM confirmed receiving.',
    )
    difference = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        help_text      = 'delivered_qty - accepted_qty. Positive = short delivery.',
    )
    bm_reason   = models.TextField(help_text='BM explanation of the discrepancy.')
    resolution  = models.CharField(
        max_length = 15,
        choices    = Resolution.choices,
        default    = Resolution.PENDING,
        db_index   = True,
    )
    resolved_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'resolved_discrepancies',
        null         = True,
        blank        = True,
    )
    resolved_at    = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'Delivery Discrepancy'
        verbose_name_plural = 'Delivery Discrepancies'

    def __str__(self):
        return (
            f"Discrepancy on {self.order.order_number} — "
            f"{self.line_item.consumable.name}: "
            f"delivered {self.delivered_qty}, accepted {self.accepted_qty}"
        )

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError(
                "DeliveryDiscrepancy records are immutable after creation."
            )
        super().save(*args, **kwargs)


class StockReturn(AuditModel):
    """
    Damaged or excess stock collected by Operations on the delivery visit.

    Collected same trip as delivery — one visit, two directions.
    Logged by the Operations officer; Finance sees it against the original clearance.
    """

    class Reason(models.TextChoices):
        DAMAGED   = 'DAMAGED',   'Damaged Stock'
        EXCESS    = 'EXCESS',    'Excess / Overstock'
        EXPIRED   = 'EXPIRED',   'Expired'
        OTHER     = 'OTHER',     'Other'

    order = models.ForeignKey(
        'procurement.ReplenishmentOrder',
        on_delete    = models.PROTECT,
        related_name = 'stock_returns',
        help_text    = 'The delivery order on which this return was collected.',
    )
    consumable = models.ForeignKey(
        'inventory.ConsumableItem',
        on_delete    = models.PROTECT,
        related_name = 'stock_returns',
    )
    quantity = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
    )
    reason = models.CharField(
        max_length = 10,
        choices    = Reason.choices,
        default    = Reason.DAMAGED,
    )
    reason_notes = models.TextField(blank=True)
    collected_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'stock_returns_collected',
    )
    confirmed_by_bm = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'stock_returns_confirmed',
        null         = True,
        blank        = True,
        help_text    = 'BM who confirmed the return at point of collection.',
    )

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'Stock Return'
        verbose_name_plural = 'Stock Returns'

    def __str__(self):
        return (
            f"Return: {self.quantity} × {self.consumable.name} "
            f"from {self.order.branch.name} [{self.reason}]"
        )