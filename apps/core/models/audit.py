from django.db import models


class AuditModel(models.Model):
    """
    Abstract base model for all Octos models.
    Provides automatic audit trail fields on every model.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']