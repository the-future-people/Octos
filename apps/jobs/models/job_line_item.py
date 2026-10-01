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
        self._reconcile_pages()
        if not self.label:
            self.label = self._build_label()
        super().save(*args, **kwargs)

    def _reconcile_pages(self):
        """
        The spec's page count wins over the column.

        pages lives in two places — this column and, for any service
        whose spec_template declares it, inside specifications. The New
        Job form sends it to the spec; pricing reads the column. For one
        morning they disagreed, and every multi-page job was charged as
        a single page: ten copies of a two-page document billed as ten
        single sheets.

        Reconciled here rather than in each of the four places a line
        item is created, because the fifth would have been missed too.
        """
        spec_pages = (self.specifications or {}).get('pages')
        if spec_pages in (None, ''):
            return
        try:
            pages = int(spec_pages)
        except (TypeError, ValueError):
            # A spec value that is not a number says nothing about the
            # page count. The column stands.
            return
        if pages > 0:
            self.pages = pages

    def _build_label(self) -> str:
        """
        Builds a clean human-readable label for the line item.
        Examples:
          "A4 Colour Photocopy — 20pp × 3 sets"
          "Spiral Binding — 3 sets"
          "Brown Envelope — 5 pcs"
        """
        service_name = self.service.name

        # Only prepend paper_size if service name doesn't already contain a size
        SIZES = ('A1', 'A2', 'A3', 'A4', 'A5')
        name_has_size = any(s in service_name.upper() for s in SIZES)

        if self.paper_size and self.paper_size not in ('', 'NA') and not name_has_size:
            label = f"{self.paper_size} {service_name}"
        else:
            label = service_name

        # Quantity suffix
        if self.pages > 1 and self.sets > 1:
            label += f" — {self.pages}pp × {self.sets} sets"
        elif self.pages > 1:
            label += f" — {self.pages}pp"
        elif self.sets > 1:
            label += f" — {self.sets} sets"
        elif self.quantity > 1:
            label += f" — {self.quantity} pcs"

        return label