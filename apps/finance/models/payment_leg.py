from django.db import models
from apps.core.models import AuditModel


class PaymentLeg(AuditModel):
    """
    Represents a single payment leg within a split payment.
    A job can have at most 2 legs — e.g. MoMo + Cash.

    Rules:
    - All legs for a job must sum exactly to the job's amount_paid
    - MoMo legs require a reference number (11 digits)
    - POS legs require an approval code
    - Cash legs have no reference requirement
    - Immutable once created — no edits ever
    """

    class Method(models.TextChoices):
        CASH = 'CASH', 'Cash'
        MOMO = 'MOMO', 'Mobile Money'
        POS  = 'POS',  'POS'

    job     = models.ForeignKey(
        'jobs.Job',
        on_delete    = models.PROTECT,
        related_name = 'payment_legs',
    )
    receipt = models.ForeignKey(
        'finance.Receipt',
        on_delete    = models.PROTECT,
        related_name = 'payment_legs',
        null         = True,
        blank        = True,
    )
    payment_method    = models.CharField(max_length=10, choices=Method.choices)
    amount            = models.DecimalField(max_digits=10, decimal_places=2)
    momo_reference    = models.CharField(max_length=20, blank=True)
    pos_approval_code = models.CharField(max_length=50, blank=True)
    sequence          = models.PositiveSmallIntegerField(
        default=1,
        help_text='1 for first leg, 2 for second leg',
    )

    class Meta:
        ordering        = ['job', 'sequence']
        verbose_name        = 'Payment Leg'
        verbose_name_plural = 'Payment Legs'

    def __str__(self):
        return f"{self.job.job_number} — Leg {self.sequence}: {self.payment_method} GHS {self.amount}"