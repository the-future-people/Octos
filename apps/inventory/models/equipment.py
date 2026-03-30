import uuid
from django.db import models
from apps.core.models import AuditModel


def _generate_asset_code(branch_code: str, pk: int) -> str:
    """
    Generate a unique asset code for a piece of equipment.
    Format: WLB-EQP-0001
    """
    return f"{branch_code.upper()}-EQP-{pk:04d}"


class BranchEquipment(AuditModel):
    """
    A physical piece of equipment owned by a branch.

    Each equipment record gets a unique asset_code on first save,
    which is used to generate a QR code for physical asset tagging.

    Equipment is branch-scoped — each branch manages its own assets.
    When HQ portal is built, equipment will be viewable by belt/region/branch.

    Condition lifecycle:
      GOOD         — fully operational, no issues
      FAIR         — working but showing wear
      NEEDS_SERVICE — scheduled or overdue maintenance
      OUT_OF_SERVICE — broken or decommissioned
    """

    class Condition(models.TextChoices):
        GOOD          = 'GOOD',          'Good'
        FAIR          = 'FAIR',          'Fair'
        NEEDS_SERVICE = 'NEEDS_SERVICE', 'Needs Service'
        OUT_OF_SERVICE= 'OUT_OF_SERVICE','Out of Service'

    branch       = models.ForeignKey(
        'organization.Branch',
        on_delete    = models.PROTECT,
        related_name = 'equipment',
    )
    name         = models.CharField(
        max_length = 200,
        help_text  = 'Equipment name e.g. Canon iR-ADV 5531i Printer',
    )
    asset_code   = models.CharField(
        max_length = 20,
        unique     = True,
        blank      = True,
        help_text  = 'Auto-generated unique asset tag e.g. WLB-EQP-0001',
    )
    quantity     = models.PositiveIntegerField(
        default  = 1,
        help_text= 'Number of units of this equipment at the branch',
    )
    condition    = models.CharField(
        max_length = 15,
        choices    = Condition.choices,
        default    = Condition.GOOD,
    )
    serial_number = models.CharField(
        max_length = 100,
        blank      = True,
        help_text  = 'Serial number(s) — separate multiple with commas',
    )
    model_number  = models.CharField(
        max_length = 100,
        blank      = True,
    )
    manufacturer  = models.CharField(
        max_length = 100,
        blank      = True,
    )
    purchase_date = models.DateField(
        null  = True, blank = True,
        help_text = 'Date equipment was purchased',
    )
    purchase_price = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        null           = True, blank = True,
        help_text      = 'Purchase price in GHS',
    )
    warranty_expiry = models.DateField(
        null  = True, blank = True,
        help_text = 'Warranty expiry date',
    )
    last_serviced = models.DateField(
        null  = True, blank = True,
        help_text = 'Date of last service or maintenance',
    )
    next_service_due = models.DateField(
        null  = True, blank = True,
        help_text = 'Scheduled next service date',
    )
    location      = models.CharField(
        max_length = 100,
        blank      = True,
        help_text  = 'Physical location within branch e.g. Front Desk, Production Room',
    )
    notes         = models.TextField(blank=True)
    is_active     = models.BooleanField(
        default   = True,
        help_text = 'False = decommissioned / removed from branch',
    )

    class Meta:
        ordering            = ['branch', 'name']
        verbose_name        = 'Branch Equipment'
        verbose_name_plural = 'Branch Equipment'

    def __str__(self):
        return f"{self.branch.code} | {self.asset_code} | {self.name}"

    def save(self, *args, **kwargs):
        """Auto-generate asset_code on first save."""
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.asset_code:
            self.asset_code = _generate_asset_code(self.branch.code, self.pk)
            BranchEquipment.objects.filter(pk=self.pk).update(asset_code=self.asset_code)

    @property
    def service_status(self):
        """Quick status for UI badges."""
        from django.utils import timezone
        today = timezone.localdate()
        if self.condition == self.Condition.OUT_OF_SERVICE:
            return 'OUT_OF_SERVICE'
        if self.condition == self.Condition.NEEDS_SERVICE:
            return 'NEEDS_SERVICE'
        if self.next_service_due and self.next_service_due <= today:
            return 'OVERDUE'
        return self.condition


class MaintenanceLog(AuditModel):
    """
    Immutable log of maintenance and service events for a piece of equipment.

    Every service, repair, inspection or replacement is recorded here.
    Cannot be edited once created — full audit trail.

    Log types:
      ROUTINE     — scheduled routine maintenance
      REPAIR      — unscheduled repair
      REPLACEMENT — part replaced
      INSPECTION  — formal inspection only, no work done
      OTHER       — anything else
    """

    class LogType(models.TextChoices):
        ROUTINE     = 'ROUTINE',     'Routine Maintenance'
        REPAIR      = 'REPAIR',      'Repair'
        REPLACEMENT = 'REPLACEMENT', 'Part Replacement'
        INSPECTION  = 'INSPECTION',  'Inspection'
        OTHER       = 'OTHER',       'Other'

    equipment      = models.ForeignKey(
        BranchEquipment,
        on_delete    = models.PROTECT,
        related_name = 'maintenance_logs',
    )
    log_type       = models.CharField(
        max_length = 15,
        choices    = LogType.choices,
        default    = LogType.ROUTINE,
    )
    service_date   = models.DateField(
        help_text = 'Date the service or repair was performed',
    )
    description    = models.TextField(
        help_text = 'What was done — be specific',
    )
    performed_by   = models.CharField(
        max_length = 150,
        help_text  = 'Technician name or company who performed the work',
    )
    cost           = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        null           = True, blank = True,
        help_text      = 'Cost of service in GHS',
    )
    parts_replaced = models.TextField(
        blank     = True,
        help_text = 'List any parts that were replaced',
    )
    next_due       = models.DateField(
        null      = True, blank = True,
        help_text = 'Recommended date for next service',
    )
    condition_after = models.CharField(
        max_length = 15,
        choices    = BranchEquipment.Condition.choices,
        help_text  = 'Equipment condition after this service',
    )
    logged_by      = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'maintenance_logs_recorded',
    )
    notes          = models.TextField(blank=True)

    class Meta:
        ordering            = ['-service_date', '-created_at']
        verbose_name        = 'Maintenance Log'
        verbose_name_plural = 'Maintenance Logs'

    def __str__(self):
        return (
            f"{self.equipment.asset_code} | {self.log_type} | {self.service_date}"
        )

    def save(self, *args, **kwargs):
        """
        On save, update the parent equipment's condition,
        last_serviced and next_service_due fields.
        Immutable after creation.
        """
        if self.pk:
            raise ValueError('MaintenanceLog records are immutable and cannot be edited.')
        super().save(*args, **kwargs)
        # Update equipment record
        BranchEquipment.objects.filter(pk=self.equipment_id).update(
            condition        = self.condition_after,
            last_serviced    = self.service_date,
            next_service_due = self.next_due,
        )