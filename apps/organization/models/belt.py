from django.db import models
from apps.core.models import AuditModel


class Belt(AuditModel):
    """
    Represents one of the three geographic belts:
    Southern, Middle, or Northern.
    """
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name