from django.db import models
from apps.core.models import AuditModel


class JobLineItem(AuditModel):
    """
    A single service within a job transaction.

    A job can have one or many line items. Each line item represents
    one service requested by the customer — e.g. "A4 Colour Photocopy,
    20 pages × 3 sets" or "Spiral Binding × 3 sets".

    Pricing is captured at the time the line item is added, so price
    changes do not retroactively affect existing jobs.
    """

    # ── File source choices ───────────────────────────────────────
    HARDCOPY = 'HARDCOPY'
    WHATSAPP = 'WHATSAPP'
    EMAIL    = 'EMAIL'
    USB      = 'USB'
    TYPING   = 'TYPING'
    NA       = 'NA'

    FILE_SOURCE_CHOICES = [
        (HARDCOPY, 'Walk-in Hardcopy'),
        (WHATSAPP, 'WhatsApp'),
        (EMAIL,    'Email'),
        (USB,      'USB Storage'),
        (TYPING,   'Typing Request'),
        (NA,       'Not Applicable'),
    ]

    # ── Sides choices ─────────────────────────────────────────────
    SINGLE = 'SINGLE'
    DOUBLE = 'DOUBLE'

    SIDES_CHOICES = [
        (SINGLE, 'Single-sided'),
        (DOUBLE, 'Double-sided'),
    ]

    # ── Relationships ─────────────────────────────────────────────
    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='line_items',
    )
    service = models.ForeignKey(
        'jobs.Service',
        on_delete=models.PROTECT,
        related_name='line_items',
    )

    # ── Quantity parameters (used by PricingEngine) ───────────────
    quantity   = models.PositiveIntegerField(default=1)
    pages      = models.PositiveIntegerField(default=1)
    sets       = models.PositiveIntegerField(default=1)
    is_color   = models.BooleanField(default=False)
    paper_size = models.CharField(max_length=10, blank=True, default='A4')
    sides      = models.CharField(
        max_length=10,
        choices=SIDES_CHOICES,
        default=SINGLE,
    )

    # ── Extra specs ───────────────────────────────────────────────
    # Stores service-specific extras: binding type, card type,
    # lamination size, etc. Keyed by spec_template fields from Service.
    specifications = models.JSONField(default=dict, blank=True)

    # ── File source ───────────────────────────────────────────────
    file_source = models.CharField(
        max_length=20,
        choices=FILE_SOURCE_CHOICES,
        default=NA,
    )

    # ── Pricing ───────────────────────────────────────────────────
    # Captured at time of adding — not affected by future price changes
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Price per unit at time of recording',
    )
    line_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='unit_price × quantity (or as calculated by PricingEngine)',
    )

    # ── Display ───────────────────────────────────────────────────
    # Auto-generated from params but can be overridden
    label    = models.CharField(max_length=255, blank=True)
    position = models.PositiveSmallIntegerField(
        default=0,
        help_text='Sort order within the job — lower = shown first',
    )

    class Meta:
        ordering = ['position', 'created_at']

    def __str__(self):
        return (
            f"{self.job.job_number} — "
            f"{self.service.name} × {self.quantity} = GHS {self.line_total}"
        )

    def save(self, *args, **kwargs):
        if not self.label:
            self.label = self._build_label()
        super().save(*args, **kwargs)

    def _build_label(self) -> str:
        """
        Auto-generates a human-readable label for the line item.
        Examples:
          "A4 Colour Photocopy — 20pp × 3 sets"
          "Spiral Binding × 3 sets"
          "Brown Envelope × 5"
        """
        parts = [self.service.name]

        if self.paper_size and self.paper_size not in ('', 'NA'):
            parts[0] = f"{self.paper_size} {parts[0]}"

        color_label = 'Colour' if self.is_color else 'B&W'
        # Only add color label for print/copy services (not binding, envelopes etc.)
        if self.service.category == 'INSTANT' and self.pages > 1:
            parts.append(color_label)

        if self.sides == self.DOUBLE:
            parts.append('2-sided')

        qty_parts = []
        if self.pages > 1:
            qty_parts.append(f'{self.pages}pp')
        if self.sets > 1:
            qty_parts.append(f'× {self.sets} sets')
        elif self.quantity > 1:
            qty_parts.append(f'× {self.quantity}')

        if qty_parts:
            parts.append(' '.join(qty_parts))

        return ' — '.join([parts[0], ' '.join(parts[1:])]) if len(parts) > 1 else parts[0]