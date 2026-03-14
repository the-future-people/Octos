from django.db import models
from apps.core.models import AuditModel


class ProformaInvoice(AuditModel):
    """
    A formal price quotation issued to a customer before payment.
    Common for corporate, school and church procurement processes.

    Lifecycle:
    DRAFT → ISSUED → CONVERTED (customer paid, job created)
                   → EXPIRED   (7 days passed, no payment)

    When a proforma converts, a Job is auto-created pre-filled
    with the proforma's line items — no double entry.

    Proforma numbers follow the format:
    PFI-{BRANCH_CODE}-{YEAR}-{SEQUENCE}
    Example: PFI-NTB-2026-00001

    Pricing is honoured within 7 days. After expiry a new proforma
    must be issued at current rates.
    """

    class Status(models.TextChoices):
        DRAFT     = 'DRAFT',     'Draft'
        ISSUED    = 'ISSUED',    'Issued'
        CONVERTED = 'CONVERTED', 'Converted to Job'
        EXPIRED   = 'EXPIRED',   'Expired'

    branch      = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='proforma_invoices',
    )
    job         = models.OneToOneField(
        'jobs.Job',
        on_delete=models.PROTECT,
        related_name='proforma_invoice',
        null=True,
        blank=True,
        help_text='Populated when proforma converts to a real job',
    )

    # ── Proforma number ───────────────────────────────────────
    proforma_number = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
    )
    sequence        = models.PositiveIntegerField(
        editable=False,
        help_text='Auto-incremented sequence per branch per year',
    )

    # ── Recipient ─────────────────────────────────────────────
    issued_to       = models.CharField(
        max_length=150,
        help_text='Organisation or individual name',
    )
    contact_person  = models.CharField(
        max_length=100,
        blank=True,
        help_text='Contact person at the organisation',
    )
    contact_phone   = models.CharField(max_length=20, blank=True)
    contact_email   = models.EmailField(blank=True)

    # ── Validity ──────────────────────────────────────────────
    issued_at       = models.DateTimeField(null=True, blank=True)
    valid_until     = models.DateField(
        help_text='7 days from issue date — system enforced',
    )
    status          = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    # ── Line items ────────────────────────────────────────────
    line_items      = models.JSONField(
        default=list,
        help_text=(
            'List of dicts: '
            '[{service_id, service_name, quantity, unit_price, total}, ...]'
        ),
    )

    # ── Totals ────────────────────────────────────────────────
    subtotal        = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    vat_amount      = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='0 until branch is GRA registered',
    )
    nhil_amount     = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    getfund_amount  = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    total           = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    # ── Staff ─────────────────────────────────────────────────
    issued_by       = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='proformas_issued',
    )

    # ── Conversion ────────────────────────────────────────────
    converted_at    = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp when customer paid and job was created',
    )
    converted_by    = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='proformas_converted',
        null=True,
        blank=True,
    )

    # ── Notes ─────────────────────────────────────────────────
    notes           = models.TextField(blank=True)

    class Meta:
        ordering        = ['-created_at']
        verbose_name        = 'Proforma Invoice'
        verbose_name_plural = 'Proforma Invoices'

    def __str__(self) -> str:
        return f"{self.proforma_number} — {self.issued_to} — {self.status}"

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone
        if self.status == self.Status.EXPIRED:
            return True
        if self.valid_until and self.status == self.Status.ISSUED:
            return timezone.now().date() > self.valid_until
        return False

    @property
    def is_convertible(self) -> bool:
        """True if proforma can still be converted to a job."""
        return self.status == self.Status.ISSUED and not self.is_expired

    @classmethod
    def generate_proforma_number(cls, branch_code: str, year: int) -> tuple[str, int]:
        """
        Generate the next sequential proforma number for a branch and year.
        Returns a tuple of (proforma_number, sequence).
        Call inside a transaction to avoid race conditions.
        """
        last = (
            cls.objects
            .filter(
                proforma_number__startswith=f"PFI-{branch_code}-{year}-"
            )
            .order_by('-sequence')
            .first()
        )
        sequence         = (last.sequence + 1) if last else 1
        proforma_number  = f"PFI-{branch_code}-{year}-{sequence:05d}"
        return proforma_number, sequence