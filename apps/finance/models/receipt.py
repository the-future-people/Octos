from django.db import models
from apps.core.models import AuditModel


class Receipt(AuditModel):
    """
    Auto-generated on every payment confirmation.

    Each receipt has its own sequential number per branch per year.
    Format: RCP-{BRANCH_CODE}-{YEAR}-{SEQUENCE}
    Example: RCP-NTB-2026-00001

    Two formats are generated:
    - Digital: sent via WhatsApp/SMS to customer
    - Thermal: formatted for 80mm POS receipt printer

    Receipts are immutable once issued — no edits ever.
    VAT fields are present but zero until branch is GRA registered.
    """

    class DeliveryStatus(models.TextChoices):
        PENDING   = 'PENDING',   'Pending'
        SENT      = 'SENT',      'Sent'
        FAILED    = 'FAILED',    'Failed'
        PRINTED   = 'PRINTED',   'Printed'

    class PaymentMethod(models.TextChoices):
        CASH   = 'CASH',   'Cash'
        MOMO   = 'MOMO',   'Mobile Money'
        POS    = 'POS',    'POS'
        CREDIT = 'CREDIT', 'Credit Account'

    job           = models.ForeignKey(
        'jobs.Job',
        on_delete=models.PROTECT,
        related_name='receipts',
    )
    daily_sheet   = models.ForeignKey(
        'finance.DailySalesSheet',
        on_delete=models.PROTECT,
        related_name='receipts',
    )
    cashier       = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='receipts_issued',
    )

    # ── Receipt number ────────────────────────────────────────
    receipt_number  = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
    )
    sequence        = models.PositiveIntegerField(
        editable=False,
        help_text='Auto-incremented sequence per branch per year',
    )

    # ── Payment details ───────────────────────────────────────
    payment_method    = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
    )
    amount_paid       = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )
    balance_due       = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    momo_reference    = models.CharField(
        max_length=50,
        blank=True,
        help_text='MoMo transaction reference — mandatory for MoMo payments',
    )
    pos_approval_code = models.CharField(
        max_length=50,
        blank=True,
        help_text='POS approval code — mandatory for POS payments',
    )

    # ── Customer details (snapshot at time of issue) ──────────
    customer_name     = models.CharField(max_length=150, blank=True)
    customer_phone    = models.CharField(max_length=20, blank=True)
    company_name      = models.CharField(
        max_length=150,
        blank=True,
        help_text='Company or sender name — shown on receipt when provided',
    )

    # ── VAT (future-proofed, zero until GRA registered) ───────
    subtotal          = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    vat_rate          = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text='VAT rate at time of issue — 0 until GRA registered',
    )
    vat_amount        = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    nhil_amount       = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='NHIL levy — 0 until GRA registered',
    )
    getfund_amount    = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='GetFund levy — 0 until GRA registered',
    )

    # ── Delivery ──────────────────────────────────────────────
    whatsapp_status   = models.CharField(
        max_length=10,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
    )
    whatsapp_sent_at  = models.DateTimeField(null=True, blank=True)
    print_status      = models.CharField(
        max_length=10,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
    )
    printed_at        = models.DateTimeField(null=True, blank=True)

    # ── Immutability guard ────────────────────────────────────
    is_void           = models.BooleanField(
        default=False,
        help_text='True only if job was voided — receipt retained for audit',
    )

    class Meta:
        ordering        = ['-created_at']
        verbose_name        = 'Receipt'
        verbose_name_plural = 'Receipts'

    def __str__(self) -> str:
        return f"{self.receipt_number} — GHS {self.amount_paid}"

    @property
    def is_fully_paid(self) -> bool:
        return self.balance_due == 0

    @classmethod
    def generate_receipt_number(cls, branch_code: str, year: int) -> tuple[str, int]:
        """
        Generate the next sequential receipt number for a branch and year.
        Returns a tuple of (receipt_number, sequence).
        Called inside a transaction to avoid race conditions.
        """
        last = (
            cls.objects
            .filter(
                receipt_number__startswith=f"RCP-{branch_code}-{year}-"
            )
            .order_by('-sequence')
            .first()
        )
        sequence       = (last.sequence + 1) if last else 1
        receipt_number = f"RCP-{branch_code}-{year}-{sequence:05d}"
        return receipt_number, sequence