from django.db import models
from django.utils import timezone
from apps.core.models import AuditModel
from .region import Region


class Branch(AuditModel):
    """
    Represents a physical branch location.
    HQ is a branch with is_headquarters=True.
    Regional HQs have is_regional_hq=True.
    """

    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name='branches',
        null=True,
        blank=True,  # null for HQ
    )
    name            = models.CharField(max_length=150)
    code            = models.CharField(max_length=20, unique=True)
    is_headquarters = models.BooleanField(default=False)
    is_regional_hq  = models.BooleanField(default=False)
    address         = models.TextField()
    phone           = models.CharField(max_length=20, blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    email           = models.EmailField(blank=True)
    capacity_score  = models.PositiveIntegerField(default=100)
    current_load    = models.PositiveIntegerField(default=0)
    is_active       = models.BooleanField(default=True)
    services        = models.ManyToManyField(
        'jobs.Service',
        blank=True,
        related_name='branches',
        help_text='Services offered at this branch',
    )

    # ── Operating hours ───────────────────────────────────────
    opening_time    = models.TimeField(
        default=timezone.datetime.strptime('08:00', '%H:%M').time(),
        help_text='Branch opening time — default 08:00',
    )
    closing_time    = models.TimeField(
        default=timezone.datetime.strptime('19:30', '%H:%M').time(),
        help_text='Branch closing time — default 19:30',
    )

    # ── VAT (future-proofed — 0 until GRA registered) ─────────
    vat_registered  = models.BooleanField(
        default=False,
        help_text='Flip to True when branch is GRA VAT registered',
    )
    vat_number      = models.CharField(
        max_length=20,
        blank=True,
        help_text='GRA VAT registration number',
    )
    vat_rate        = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text='VAT rate — 0.00 until registered, then 15.00',
    )
    nhil_rate       = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text='NHIL levy rate — 0.00 until registered, then 2.50',
    )
    getfund_rate    = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text='GetFund levy rate — 0.00 until registered, then 2.50',
    )

    class Meta:
        ordering        = ['name']
        verbose_name_plural = 'Branches'

    def __str__(self) -> str:
        return self.name

    @property
    def load_percentage(self) -> float:
        if self.capacity_score == 0:
            return 0
        return round((self.current_load / self.capacity_score) * 100, 1)

    @property
    def is_available(self) -> bool:
        return self.load_percentage < 85

    @property
    def total_tax_rate(self) -> float:
        """Combined VAT + NHIL + GetFund rate."""
        return float(self.vat_rate) + float(self.nhil_rate) + float(self.getfund_rate)