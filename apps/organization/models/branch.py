from django.db import models
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
        blank=True  # null for HQ
    )
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, unique=True)
    is_headquarters = models.BooleanField(default=False)
    is_regional_hq = models.BooleanField(default=False)
    address = models.TextField()
    phone = models.CharField(max_length=20, blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    capacity_score = models.PositiveIntegerField(default=100)
    current_load = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    services = models.ManyToManyField(
        'jobs.Service',
        blank=True,
        related_name='branches',
        help_text='Services offered at this branch'
    )

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Branches'

    def __str__(self):
        return self.name

    @property
    def load_percentage(self):
        if self.capacity_score == 0:
            return 0
        return round((self.current_load / self.capacity_score) * 100, 1)

    @property
    def is_available(self):
        return self.load_percentage < 85