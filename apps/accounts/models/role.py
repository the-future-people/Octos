from django.db import models
from apps.core.models import AuditModel


class Permission(AuditModel):
    """
    A single permission codename.
    e.g. 'can_route_job', 'can_confirm_payment'
    """
    codename = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255)

    def __str__(self):
        return self.codename


class Role(AuditModel):
    """
    A role groups permissions together.
    Every user has exactly one role.
    """
    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=100)
    permissions = models.ManyToManyField(
        Permission,
        blank=True,
        related_name='roles'
    )

    def __str__(self):
        return self.display_name