from django.db import models
from apps.core.models import AuditModel


class Invoice(AuditModel):
    """
    A formal invoice — either linked to an existing job (auto-filled)
    or standalone (service catalogue selected manually).
    """

    # ── Types ─────────────────────────────────────────────────
    PROFORMA   = 'PROFORMA'
    TAX        = 'TAX'

    TYPE_CHOICES = [
        (PROFORMA, 'Proforma Invoice'),
        (TAX,      'Tax Invoice'),
    ]

    # ── Status ────────────────────────────────────────────────
    DRAFT  = 'DRAFT'
    SENT   = 'SENT'
    VIEWED = 'VIEWED'
    PAID   = 'PAID'

    STATUS_CHOICES = [
        (DRAFT,  'Draft'),
        (SENT,   'Sent'),
        (VIEWED, 'Viewed'),
        (PAID,   'Paid'),
    ]

    # ── Delivery ──────────────────────────────────────────────
    WHATSAPP = 'WHATSAPP'
    EMAIL    = 'EMAIL'
    BOTH     = 'BOTH'

    DELIVERY_CHOICES = [
        (WHATSAPP, 'WhatsApp'),
        (EMAIL,    'Email'),
        (BOTH,     'Both'),
    ]

    # ── Core ──────────────────────────────────────────────────
    branch         = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='invoices',
    )
    job            = models.ForeignKey(
        'jobs.Job',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices',
        help_text='Leave blank for standalone invoices',
    )
    generated_by   = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='invoices_generated',
    )

    # ── Invoice meta ──────────────────────────────────────────
    invoice_number  = models.CharField(max_length=40, unique=True, blank=True)
    invoice_type    = models.CharField(max_length=20, choices=TYPE_CHOICES, default=PROFORMA)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    issue_date      = models.DateField(auto_now_add=True)
    due_date        = models.DateField(null=True, blank=True)
    bm_note         = models.TextField(blank=True)

    # ── Bill To ───────────────────────────────────────────────
    bill_to_name    = models.CharField(max_length=150)
    bill_to_phone   = models.CharField(max_length=30, blank=True)
    bill_to_email   = models.EmailField(blank=True)
    bill_to_company = models.CharField(max_length=150, blank=True)

    # ── Delivery ──────────────────────────────────────────────
    delivery_channel = models.CharField(
        max_length=20,
        choices=DELIVERY_CHOICES,
        default=WHATSAPP,
    )
    sent_at          = models.DateTimeField(null=True, blank=True)

    # ── Financials ────────────────────────────────────────────
    subtotal        = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    vat_rate        = models.DecimalField(max_digits=5,  decimal_places=2, default=0)
    vat_amount      = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total           = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── PDF ───────────────────────────────────────────────────
    pdf_path        = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'Invoice'
        verbose_name_plural = 'Invoices'

    def __str__(self):
        return f"{self.invoice_number} — {self.bill_to_name} ({self.invoice_type})"

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self._generate_number()
        super().save(*args, **kwargs)

    def _generate_number(self):
        from django.utils import timezone
        year   = timezone.now().year
        code   = self.branch.code if self.branch else 'GEN'
        prefix = f"INV-{code}-{year}-"
        last   = Invoice.objects.filter(
            invoice_number__startswith=prefix
        ).count() + 1
        return f"{prefix}{str(last).zfill(4)}"

    def compute_totals(self):
        """Recompute subtotal, VAT and total from line items."""
        self.subtotal   = sum(li.line_total for li in self.line_items.all())
        self.vat_amount = (self.subtotal * self.vat_rate / 100).quantize(
            self.subtotal
        )
        self.total      = self.subtotal + self.vat_amount


class InvoiceLineItem(AuditModel):
    """
    A single line on an invoice.
    Used for both job-linked and standalone invoices.
    """
    invoice    = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='line_items',
    )
    service    = models.ForeignKey(
        'jobs.Service',
        on_delete=models.PROTECT,
        related_name='invoice_line_items',
    )
    label      = models.CharField(max_length=200)
    quantity   = models.PositiveIntegerField(default=1)
    pages      = models.PositiveIntegerField(default=1)
    sets       = models.PositiveIntegerField(default=1)
    is_color   = models.BooleanField(default=False)
    paper_size = models.CharField(max_length=20, default='A4')
    sides      = models.CharField(max_length=20, default='SINGLE')
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    position   = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position']

    def __str__(self):
        return f"{self.invoice.invoice_number} — {self.label}"