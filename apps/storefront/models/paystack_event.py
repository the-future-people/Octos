"""
Every webhook event, stored once.

Paystack retries. A network blip, a slow response, a deploy mid-request
— any of them means the same event arrives again, and a payment counted
twice is money the books cannot explain.

So the reference is unique, and the write that records an event is what
decides whether it has been seen. Not a check followed by a write, which
two simultaneous deliveries would both pass: the database constraint
refuses the second, and the refusal is the answer.

The raw body is kept because a payment dispute is settled by what the
provider actually said, not by what we concluded from it.
"""

from django.db import models

from apps.core.models import AuditModel


class PaystackEvent(AuditModel):
    # Our own reference, sent to Paystack and echoed back. Unique, and
    # that uniqueness is the idempotency.
    reference = models.CharField(max_length=100, unique=True, db_index=True)

    event_type = models.CharField(max_length=50)

    # Paystack's own id for the transaction, for reconciling against
    # their dashboard when a figure is queried.
    provider_id = models.CharField(max_length=50, blank=True)

    # In pesewas, as sent. Converted where it is used rather than here,
    # so this stays a record of what arrived.
    amount_minor = models.BigIntegerField(default=0)

    channel = models.CharField(max_length=30, blank=True)

    # Exactly what was posted. A dispute is settled by this.
    payload = models.JSONField(default=dict, blank=True)

    order = models.ForeignKey(
        'storefront.OnlineOrder',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='payment_events',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.event_type} — {self.reference}"