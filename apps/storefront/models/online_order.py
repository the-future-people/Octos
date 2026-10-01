"""
An order that does not yet belong to anyone.

Every job in Octos is branch-shaped: a branch, a daily sheet, a
branch-scoped number, a place in a queue. An online order has none of
those. It is created by a stranger before any branch knows about it,
and it only becomes a Job once routing and payment have settled.

A Job with a null branch would leak into every queue and every sheet
total, so the order is its own record and converts at the end. The
precedent is ProformaInvoice, which is the same shape with a different
trigger: a customer-facing document that becomes a job on acceptance.

Most orders are abandoned. Someone browses, prices a banner, and closes
the tab. That is normal and costs nothing — the record expires.
"""

from decimal import Decimal

from django.db import models

from apps.core.models import AuditModel


class OnlineOrder(AuditModel):
    """
    ORD-{YEAR}-{SEQUENCE}, company-wide rather than per branch, because
    an online order belongs to Farhat before it belongs to anywhere.
    """

    class Status(models.TextChoices):
        DRAFT           = 'DRAFT',           'Being built'
        AWAITING_PAYMENT = 'AWAITING_PAYMENT', 'Awaiting payment'
        PAID            = 'PAID',            'Paid'
        CONVERTED       = 'CONVERTED',       'Converted to a job'
        ABANDONED       = 'ABANDONED',       'Abandoned'
        CANCELLED       = 'CANCELLED',       'Cancelled'

    class Fulfilment(models.TextChoices):
        COLLECTION = 'COLLECTION', 'Collection'
        DELIVERY   = 'DELIVERY',   'Delivery'

    order_number = models.CharField(max_length=30, unique=True, editable=False)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True,
    )

    # Null until they tell us who they are, which is asked for late:
    # a stranger should know what a job costs before being asked to
    # identify themselves.
    lead = models.ForeignKey(
        'storefront.Lead',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='orders',
    )

    # Null until routing. Capability decides location — which branches
    # can do this work is answerable only once the services are chosen.
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='online_orders',
    )

    # The same contract the proforma uses — service_name, quantity,
    # unit_price, total — plus the specifications the service declared.
    # A record of what was asked for at a moment, not a live thing the
    # floor edits; it becomes real line items at conversion.
    line_items = models.JSONField(default=list, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    fulfilment = models.CharField(
        max_length=20, choices=Fulfilment.choices, default=Fulfilment.COLLECTION,
    )
    delivery_address = models.TextField(blank=True)
    promised_for = models.DateField(null=True, blank=True)

    # ── Payment ───────────────────────────────────────────────────
    # Online orders are paid in full. The 70% deposit exists because the
    # customer is standing in front of you and is known; a stranger on
    # the internet is not.
    #
    # The reference is ours and goes to the provider, so a webhook can
    # name the order it belongs to. paid_at is set by the webhook, never
    # by the customer returning to the page — a customer who closes the
    # tab after paying has still paid.
    payment_reference = models.CharField(
        max_length=100, blank=True, db_index=True,
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    # ── Conversion ────────────────────────────────────────────────
    job = models.OneToOneField(
        'jobs.Job',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='online_order',
    )
    converted_at = models.DateTimeField(null=True, blank=True)

    # An unfinished order is swept rather than kept forever. Most orders
    # are abandoned and that is fine.
    expires_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.order_number} — {self.status}"

    @property
    def is_paid(self):
        return self.paid_at is not None

    @property
    def is_open(self):
        return self.status in (self.Status.DRAFT, self.Status.AWAITING_PAYMENT)

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self._next_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_number():
        """
        From a database sequence, not from the highest number so far.

        Reading the maximum and adding one is what the proforma and the
        receipt do, and it is safe when one member of staff creates one
        document at a time. Two strangers can click in the same
        millisecond, and both would compute the same number: one order
        would fail on the unique constraint for no reason the customer
        could understand.
        """
        from django.db import connection
        from django.utils import timezone

        year = timezone.localdate().year
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval('storefront_order_seq')")
            sequence = cursor.fetchone()[0]
        return f"ORD-{year}-{sequence:05d}"