from django.db import models
from apps.core.models import AuditModel


class WeeklyReport(AuditModel):
    """
    Represents a week's consolidated operations filing for a branch.
    Covers Monday to Saturday (Sunday is always closed).
    One report per branch per week — filed by the BM every Saturday.

    Rules:
    - Can only be submitted when all expected daily sheets are CLOSED
    - Once SUBMITTED → status moves to LOCKED — immutable
    - Revenue figures are aggregated from daily sheets at prepare time
    - inventory_snapshot is an empty dict until the inventory app populates it
    - PDF is generated on submit and stored for download
    """

    class Status(models.TextChoices):
        DRAFT     = 'DRAFT',     'Draft'
        SUBMITTED = 'SUBMITTED', 'Submitted'
        LOCKED    = 'LOCKED',    'Locked'

    branch      = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='weekly_reports',
    )

    # ── Week identification ───────────────────────────────────────────────
    week_number = models.PositiveIntegerField(
        help_text='ISO week number (1–52)',
    )
    year        = models.PositiveIntegerField()
    date_from   = models.DateField(help_text='Monday of the week')
    date_to     = models.DateField(help_text='Saturday of the week')

    status      = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    # ── Linked daily sheets (Mon–Sat, up to 6) ───────────────────────────
    daily_sheets = models.ManyToManyField(
        'finance.DailySalesSheet',
        blank=True,
        related_name='weekly_reports',
    )

    # ── Aggregated revenue (frozen on submit) ─────────────────────────────
    total_cash           = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_momo           = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_pos            = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_petty_cash_out = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_credit_issued  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_cash_in_till     = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Job summary (frozen on submit) ───────────────────────────────────
    total_jobs_created   = models.PositiveIntegerField(default=0)
    total_jobs_complete  = models.PositiveIntegerField(default=0)
    total_jobs_cancelled = models.PositiveIntegerField(default=0)
    carry_forward_count  = models.PositiveIntegerField(
        default=0,
        help_text='Jobs still pending payment at week end',
    )

    # ── Inventory hook (populated by inventory app later) ─────────────────
    inventory_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text='Populated by inventory app — consumables used this week',
    )

    # ── BM notes & sign-off ───────────────────────────────────────────────
    bm_notes        = models.TextField(blank=True)
    submitted_by    = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='weekly_reports_submitted',
        null=True, blank=True,
    )
    submitted_at    = models.DateTimeField(null=True, blank=True)

    # ── PDF ───────────────────────────────────────────────────────────────
    pdf_path        = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering        = ['-year', '-week_number']
        unique_together = [['branch', 'week_number', 'year']]
        verbose_name        = 'Weekly Report'
        verbose_name_plural = 'Weekly Reports'

    def __str__(self) -> str:
        return f"{self.branch.code} — W{self.week_number}/{self.year} [{self.status}]"

    @property
    def total_collected(self):
        return self.total_cash + self.total_momo + self.total_pos

    @property
    def is_locked(self):
        return self.status == self.Status.LOCKED

    @property
    def sheets_count(self):
        return self.daily_sheets.count()

    @property
    def all_sheets_closed(self):
        """True only if all linked sheets are CLOSED or AUTO_CLOSED."""
        from apps.finance.models import DailySalesSheet
        sheets = self.daily_sheets.all()
        if not sheets.exists():
            return False
        return all(
            s.status in [DailySalesSheet.Status.CLOSED, DailySalesSheet.Status.AUTO_CLOSED]
            for s in sheets
        )