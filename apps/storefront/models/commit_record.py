"""
What a commit did, so a retry can be told rather than repeated.

A commit that succeeds and whose response is lost is a normal event on
mobile data. The customer presses again. Without this, that buys the
banner twice.

The key is unique, and that uniqueness is the protection: two presses
arriving together both try to write, one is refused by the database,
and the refusal is how the second knows to return the first's answer.
"""

from django.db import models

from apps.core.models import AuditModel


class CommitRecord(AuditModel):
    idempotency_key = models.CharField(max_length=64, unique=True, db_index=True)

    order = models.ForeignKey(
        'storefront.OnlineOrder',
        on_delete=models.CASCADE,
        related_name='commits',
    )

    # Exactly what was returned the first time. A retry gets this back
    # rather than a fresh answer, which might differ.
    result = models.JSONField(default=dict)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.idempotency_key[:12]} — {self.order.order_number}'