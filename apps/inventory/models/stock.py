from django.db import models
from apps.core.models import AuditModel


class BranchStock(AuditModel):
    """
    Current stock level for a consumable at a specific branch.
    Never edited directly — always updated via StockMovement.
    """
    branch     = models.ForeignKey(
        'organization.Branch',
        on_delete    = models.PROTECT,
        related_name = 'stock_levels',
    )
    consumable = models.ForeignKey(
        'inventory.ConsumableItem',
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
        'inventory.StockMovement',
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
        rp = self.consumable.reorder_point
        return rp > 0 and float(self.quantity) <= (rp * 0.5)


class StockMovement(AuditModel):
    """
    Immutable ledger of all stock movements. Append only.
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
        'inventory.ConsumableItem',
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
        if self.pk:
            raise ValueError('StockMovement records are immutable and cannot be edited.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('StockMovement records cannot be deleted.')


class WasteIncident(AuditModel):
    """
    Attendant-reported waste incident — jams, misprints, damage.
    Immutable once created.
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
        'inventory.ConsumableItem',
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
    notes          = models.TextField(blank=True)
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
        if self.pk:
            raise ValueError('WasteIncident records are immutable and cannot be edited.')
        super().save(*args, **kwargs)