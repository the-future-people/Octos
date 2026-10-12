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

    # The order number is sequential and trivially guessable, so it
    # cannot be what proves this order is yours. The token is returned
    # once at creation and required on every request afterwards — and it
    # is what the tracking link carries, so the customer reaches their
    # own order without an account.
    access_token = models.CharField(
        max_length=64, unique=True, editable=False, db_index=True,
        default='', blank=True,
    )

    short_code = models.CharField(
        max_length=8, unique=True, editable=False, db_index=True,
        default='', blank=True,
        help_text=(
            'A second key to the same door, short enough to text. The '
            'access token runs to 43 characters and a tracking link '
            'carrying it leaves no room for a message around it — an '
            'SMS has 160 before it splits in two and costs double.'
        ),
    )
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

    # Three figures, not one.
    #
    # full_total is what the work is worth at catalogue prices. total is
    # what the customer actually pays, and what the receipt, the day
    # sheet and every report count. The difference between them is the
    # discount, kept as its own number so a month's giveaway can be
    # added up — storing only what was charged would make the scheme
    # invisible the moment it had run.
    full_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_reason = models.CharField(max_length=100, blank=True)
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

    # What the customer paid is `total` above. These two are what
    # happened to it on the way in: the provider's cut, and what
    # actually reached the bank.
    #
    # Both are kept so the day sheet can show the work's full value —
    # comparable with the same job sold at the counter — and the amount
    # that has to reconcile against a bank statement. Neither number
    # stands in for the other.
    payment_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)

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
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    job = models.OneToOneField(
        'jobs.Job',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='online_order',
        help_text=(
            'The job this became, once the floor had it. Set at '
            'conversion and never changed — an order becomes work '
            'exactly once, however many times Paystack retries.'
        ),
    )

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

    def touch_expiry(self):
        """
        Push the expiry out. Called when the customer does something
        deliberate — adds an item, changes one — not when a page merely
        loads. A cart that never expires because something polls it is
        a cart that is never swept.
        """
        from django.utils import timezone
        self.expires_at = timezone.now() + timezone.timedelta(days=7)
    
    @property
    def is_open(self):
        return self.status in (self.Status.DRAFT, self.Status.AWAITING_PAYMENT)

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self._next_number()
        if not self.access_token:
            from secrets import token_urlsafe
            self.access_token = token_urlsafe(32)
        if not self.short_code:
            self.short_code = self._make_short_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _make_short_code():
        """
        Eight characters a tired eye can read off a phone.

        I, O, 1, 0 and lowercase l are left out: a code typed back in
        should not turn on a glyph. What remains gives 32^8 — about a
        thousand billion — so guessing one is not a way in.
        """
        from secrets import choice

        alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        for _ in range(8):
            code = ''.join(choice(alphabet) for _ in range(8))
            if not OnlineOrder.objects.filter(short_code=code).exists():
                return code
        # Eight collisions in a row means something is very wrong, and
        # a duplicate is worse than a loud failure.
        raise RuntimeError('Could not mint a short code')

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

    def next_payment_reference(self):
        """
        What to call this attempt at paying.

        Paystack requires a reference to be unique forever and refuses
        a second transaction reusing one. Sending the order number
        meant a customer who opened the payment page and backed out
        had bricked that order — it could never be paid, by refreshing
        or otherwise.

        So the first attempt is the order number, which is the thing a
        customer might read out, and each one after it carries a
        suffix. The reference is stored either way, so the webhook
        still finds its way back here.

        None when there is nothing to pay.
        """
        if self.is_paid:
            return None

        current = self.payment_reference or ''
        if not current:
            return self.order_number

        if current == self.order_number:
            return f'{self.order_number}-2'

        # ORD-2026-00012-3 → 4. A reference we did not mint ourselves
        # starts the count again rather than guessing at its shape.
        tail = current.rsplit('-', 1)[-1]
        if tail.isdigit() and current.startswith(self.order_number):
            return f'{self.order_number}-{int(tail) + 1}'

        return f'{self.order_number}-2'
