from django.db import models
from apps.core.models import AuditModel
from .belt import Belt


class Region(AuditModel):
    """
    Represents a region within a belt.
    e.g. Greater Accra within the Southern Belt.
    """
    belt = models.ForeignKey(
        Belt,
        on_delete=models.PROTECT,
        related_name='regions'
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        unique_together = [['belt', 'name']]

    def __str__(self):
        return f"{self.name} — {self.belt.name}"