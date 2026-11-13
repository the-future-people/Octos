from django.db import models
from django.db.models import Q
from apps.core.models import AuditModel


class AttendantSignOff(AuditModel):
    """
    An attendant's end-of-day sign-off (designed 13 Nov 2026).

    One record per attendant per day sheet. Opens at the attendant's shift end
    (recording closes at the same moment) and must be done by the sign-off
    deadline (ShiftRoleConfig.signoff_buffer). After the deadline Octos signs
    the attendant off: is_auto=True, signed_off_by = the OCTOS account.

    Testimony, not action: the sign-off records what the attendant says
    happened and moves no job axis. The one exception is NOT_PRODUCED, which
    is passed to JobStatusEngine as an ordinary cancel, so the engine's own
    rules decide whether it is allowed.

    buckets is a snapshot taken at signing. Every job the attendant recorded
    that day sits in exactly one bucket, and the counts sum to recorded_total.
    Never recalculated: jobs keep moving after sign-off, the record does not.

    Constraint: one sign-off per attendant per sheet. This is what makes the
    automatic sign-off idempotent even when it races a manual one.
    """

    attendant = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'attendant_signoffs',
    )
    daily_sheet = models.ForeignKey(
        'finance.DailySalesSheet',
        on_delete    = models.PROTECT,
        related_name = 'attendant_signoffs',
    )
    signed_off_at = models.DateTimeField()
    signed_off_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'attendant_signoffs_recorded',
        help_text    = 'The attendant, or the OCTOS system account for an automatic sign-off.',
    )
    is_auto       = models.BooleanField(default=False)
    handover_note = models.TextField(blank=True)

    buckets = models.JSONField(
        default   = dict,
        help_text = 'Snapshot at signing: {bucket: count, ..., "recorded_total": n}.',
    )
    left_unpaid_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    missing_count     = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering    = ['-signed_off_at']
        constraints = [
            models.UniqueConstraint(
                fields = ['daily_sheet', 'attendant'],
                name   = 'unique_attendant_signoff_per_sheet',
            ),
        ]

    def __str__(self):
        how = 'auto' if self.is_auto else 'signed'
        return f"{self.attendant} — {self.daily_sheet} ({how})"


class AttendantSignOffItem(AuditModel):
    """
    One answer inside a sign-off: an unpaid instant job explained, or a
    ready job checked on the shelf. LEFT_UNPAID and MISSING go to the branch
    manager, who resolves them (resolved_by / resolved_at). Whether an item
    still needs the BM is derived, never stored.
    """

    class Kind(models.TextChoices):
        UNPAID_INSTANT = 'UNPAID_INSTANT', 'Unpaid instant job'
        SHELF          = 'SHELF',          'Shelf check'

    class Answer(models.TextChoices):
        COMING_BACK  = 'COMING_BACK',  'Customer coming back'
        LEFT_UNPAID  = 'LEFT_UNPAID',  'Customer left unpaid'
        NOT_PRODUCED = 'NOT_PRODUCED', 'Not printed'
        ON_SHELF     = 'ON_SHELF',     'On shelf'
        MISSING      = 'MISSING',      'Missing from shelf'

    # Plain values: the answer read back from the database is a str.
    NEEDS_BM = {Answer.LEFT_UNPAID.value, Answer.MISSING.value}

    signoff = models.ForeignKey(
        AttendantSignOff,
        on_delete    = models.CASCADE,
        related_name = 'items',
    )
    job = models.ForeignKey(
        'jobs.Job',
        on_delete    = models.PROTECT,
        related_name = 'attendant_signoff_items',
    )
    kind   = models.CharField(max_length=20, choices=Kind.choices)
    answer = models.CharField(max_length=20, choices=Answer.choices)
    amount = models.DecimalField(
        max_digits     = 10,
        decimal_places = 2,
        default        = 0,
        help_text      = "The job's value at sign-off (snapshot).",
    )

    resolved_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        null         = True,
        blank        = True,
        related_name = 'attendant_signoff_items_resolved',
    )
    resolved_at     = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)

    class Meta:
        ordering    = ['signoff', 'kind', 'id']
        constraints = [
            models.UniqueConstraint(
                fields = ['signoff', 'job', 'kind'],
                name   = 'unique_signoff_item_per_job_kind',
            ),
            models.CheckConstraint(
                condition = (
                    Q(kind='UNPAID_INSTANT', answer__in=['COMING_BACK', 'LEFT_UNPAID', 'NOT_PRODUCED'])
                    | Q(kind='SHELF', answer__in=['ON_SHELF', 'MISSING'])
                ),
                name = 'signoff_item_answer_matches_kind',
            ),
        ]

    def __str__(self):
        return f"{self.job} — {self.get_answer_display()}"

    @property
    def needs_bm(self):
        return self.answer in self.NEEDS_BM and self.resolved_at is None