from django.db import models
from apps.core.models import AuditModel


class ConsumableCategory(AuditModel):
    """
    Top-level grouping of consumables.
    e.g. Paper, Envelopes, Binding, Lamination, Toner
    """
    name        = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    icon        = models.CharField(max_length=50, blank=True, help_text='Icon name for UI')

    class Meta:
        ordering            = ['name']
        verbose_name        = 'Consumable Category'
        verbose_name_plural = 'Consumable Categories'

    def __str__(self):
        return self.name


class ConsumableItem(AuditModel):
    """
    A specific consumable used in branch operations.

    Paper sizes follow ISO standard: A2, A3, A4, A5, Legal, Custom
    unit_type determines how stock is measured:
      SHEETS   — paper, envelopes, cards (counted individually)
      UNITS    — binding rings, pouches (counted individually)
      PERCENT  — toner cartridges (0–100%)

    reorder_point: alert BM when stock falls below this level
    reorder_qty:   suggested order quantity
    """

    class UnitType(models.TextChoices):
        SHEETS  = 'SHEETS',  'Sheets'
        UNITS   = 'UNITS',   'Units'
        PERCENT = 'PERCENT', 'Percentage'

    class PaperSize(models.TextChoices):
        A2  = 'A2',  'A2'
        A3  = 'A3',  'A3'
        A4  = 'A4',  'A4'
        A5  = 'A5',  'A5'
        NA  = 'N/A', 'Not Applicable'

    category      = models.ForeignKey(
        ConsumableCategory,
        on_delete    = models.PROTECT,
        related_name = 'items',
    )
    name          = models.CharField(max_length=150)
    description   = models.TextField(blank=True)
    paper_size    = models.CharField(
        max_length = 5,
        choices    = PaperSize.choices,
        default    = PaperSize.NA,
        help_text  = 'Paper size — N/A for non-paper items',
    )
    unit_type     = models.CharField(
        max_length = 10,
        choices    = UnitType.choices,
        default    = UnitType.SHEETS,
    )
    unit_label    = models.CharField(
        max_length = 30,
        default    = 'sheets',
        help_text  = 'Human-readable unit label e.g. sheets, pcs, %',
    )
    reorder_point = models.PositiveIntegerField(
        default    = 0,
        help_text  = 'Alert when stock falls to or below this level',
    )
    reorder_qty   = models.PositiveIntegerField(
        default    = 0,
        help_text  = 'Suggested reorder quantity',
    )
    is_active     = models.BooleanField(default=True)

    class Meta:
        ordering            = ['category', 'paper_size', 'name']
        unique_together     = [['category', 'name']]
        verbose_name        = 'Consumable Item'
        verbose_name_plural = 'Consumable Items'

    def __str__(self):
        size = f" ({self.paper_size})" if self.paper_size != self.PaperSize.NA else ''
        return f"{self.name}{size}"


class ServiceConsumable(AuditModel):
    """
    Maps a service to the consumables it uses per unit of work.
    """
    service           = models.ForeignKey(
        'jobs.Service',
        on_delete    = models.PROTECT,
        related_name = 'consumable_mappings',
    )
    consumable        = models.ForeignKey(
        ConsumableItem,
        on_delete    = models.PROTECT,
        related_name = 'service_mappings',
    )
    quantity_per_unit = models.DecimalField(
        max_digits     = 8,
        decimal_places = 4,
        default        = 1.0,
        help_text      = 'Consumable units used per 1 page/set/unit of service',
    )
    applies_to_color  = models.BooleanField(
        default    = True,
        help_text  = 'If False, only applies to B&W jobs',
    )
    applies_to_bw     = models.BooleanField(
        default    = True,
        help_text  = 'If False, only applies to color jobs',
    )
    notes             = models.TextField(blank=True)

    class Meta:
        unique_together     = [['service', 'consumable']]
        verbose_name        = 'Service Consumable'
        verbose_name_plural = 'Service Consumables'

    def __str__(self):
        return f"{self.service.name} → {self.consumable.name} ({self.quantity_per_unit}/unit)"