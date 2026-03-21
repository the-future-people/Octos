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

    quantity_per_unit: how much consumable is used per 1 unit of the service
    For printing: quantity_per_unit = 1 means 1 sheet per page printed
    For binding:  quantity_per_unit = 1 means 1 ring per bind job

    color_multiplier: if True, color jobs use more toner than BW
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
        max_digits   = 8,
        decimal_places = 4,
        default      = 1.0,
        help_text    = 'Consumable units used per 1 page/set/unit of service',
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


class BranchStock(AuditModel):
    """
    Current stock level for a consumable at a specific branch.
    This is the cached current balance — always recomputable from StockMovement.
    Never edited directly — always updated via StockMovement.
    """
    branch     = models.ForeignKey(
        'organization.Branch',
        on_delete    = models.PROTECT,
        related_name = 'stock_levels',
    )
    consumable = models.ForeignKey(
        ConsumableItem,
        on_delete    = models.PROTECT,
        related_name = 'branch_stocks',
    )
    quantity   = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        default        = 0,
        help_text      = 'Current stock level',
    )
    last_movement = models.ForeignKey(
        'StockMovement',
        on_delete    = models.SET_NULL,
        null         = True, blank = True,
        related_name = '+',
        help_text    = 'Most recent movement that updated this stock',
    )

    class Meta:
        unique_together     = [['branch', 'consumable']]
        verbose_name        = 'Branch Stock'
        verbose_name_plural = 'Branch Stock Levels'

    def __str__(self):
        return f"{self.branch.code} — {self.consumable.name}: {self.quantity} {self.consumable.unit_label}"

    @property
    def is_low(self):
        return float(self.quantity) <= self.consumable.reorder_point

    @property
    def is_critical(self):
        """True when stock is at or below 50% of reorder point."""
        rp = self.consumable.reorder_point
        return rp > 0 and float(self.quantity) <= (rp * 0.5)


class StockMovement(AuditModel):
    """
    Immutable ledger of all stock movements.
    Never edited or deleted — append only.

    Movement types:
      OPENING    — initial stock entry when system goes live
      IN         — stock received from supplier
      OUT        — consumed by job (auto-created on job completion)
      WASTE      — waste incident (jams, misprints, damage)
      CORRECTION — HQ-level correction only (requires special permission)
    """

    class MovementType(models.TextChoices):
        OPENING    = 'OPENING',    'Opening Balance'
        IN         = 'IN',         'Stock Received'
        OUT        = 'OUT',        'Job Consumption'
        WASTE      = 'WASTE',      'Waste / Spoilage'
        CORRECTION = 'CORRECTION', 'HQ Correction'

    branch        = models.ForeignKey(
        'organization.Branch',
        on_delete    = models.PROTECT,
        related_name = 'stock_movements',
    )
    consumable    = models.ForeignKey(
        ConsumableItem,
        on_delete    = models.PROTECT,
        related_name = 'movements',
    )
    movement_type = models.CharField(
        max_length = 12,
        choices    = MovementType.choices,
    )
    quantity      = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        help_text      = 'Always positive — direction determined by movement_type',
    )
    balance_after = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        help_text      = 'Stock level after this movement — snapshot for audit',
    )
    reference_job = models.ForeignKey(
        'jobs.Job',
        on_delete    = models.SET_NULL,
        null         = True, blank = True,
        related_name = 'stock_movements',
        help_text    = 'Job that triggered this movement (OUT only)',
    )
    recorded_by   = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'stock_movements_recorded',
    )
    notes         = models.TextField(blank=True)

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'Stock Movement'
        verbose_name_plural = 'Stock Movements'

    def __str__(self):
        direction = '+' if self.movement_type in ['OPENING', 'IN'] else '-'
        return (
            f"{self.branch.code} | {self.consumable.name} | "
            f"{self.movement_type} {direction}{self.quantity}"
        )

    def save(self, *args, **kwargs):
        """Prevent editing existing movements — immutable ledger."""
        if self.pk:
            raise ValueError(
                'StockMovement records are immutable and cannot be edited.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            'StockMovement records cannot be deleted.'
        )


class WasteIncident(AuditModel):
    """
    Attendant-reported waste incident — jams, misprints, damage.
    Only attendants can create these — BMs and above can only view.
    Immutable once created.

    reason choices:
      JAM       — paper jam
      MISPRINT  — print error / wrong settings
      DAMAGE    — physical damage to stock
      OTHER     — anything else
    """

    class Reason(models.TextChoices):
        JAM      = 'JAM',      'Paper Jam'
        MISPRINT = 'MISPRINT', 'Misprint / Print Error'
        DAMAGE   = 'DAMAGE',   'Physical Damage'
        OTHER    = 'OTHER',    'Other'

    branch      = models.ForeignKey(
        'organization.Branch',
        on_delete    = models.PROTECT,
        related_name = 'waste_incidents',
    )
    consumable  = models.ForeignKey(
        ConsumableItem,
        on_delete    = models.PROTECT,
        related_name = 'waste_incidents',
    )
    quantity    = models.DecimalField(
        max_digits     = 8,
        decimal_places = 2,
        help_text      = 'Number of sheets/units wasted',
    )
    reason      = models.CharField(
        max_length = 12,
        choices    = Reason.choices,
        default    = Reason.JAM,
    )
    job         = models.ForeignKey(
        'jobs.Job',
        on_delete    = models.SET_NULL,
        null         = True, blank = True,
        related_name = 'waste_incidents',
        help_text    = 'Job being worked on when waste occurred',
    )
    reported_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'waste_incidents_reported',
    )
    notes       = models.TextField(blank=True)
    stock_movement = models.OneToOneField(
        StockMovement,
        on_delete    = models.PROTECT,
        related_name = 'waste_incident',
        null         = True, blank = True,
        help_text    = 'The WASTE StockMovement created for this incident',
    )

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'Waste Incident'
        verbose_name_plural = 'Waste Incidents'

    def __str__(self):
        return (
            f"{self.branch.code} | {self.consumable.name} | "
            f"{self.reason} — {self.quantity} {self.consumable.unit_label}"
        )

    def save(self, *args, **kwargs):
        """Prevent editing existing incidents — immutable."""
        if self.pk:
            raise ValueError(
                'WasteIncident records are immutable and cannot be edited.'
            )
        super().save(*args, **kwargs)