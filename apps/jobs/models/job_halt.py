from django.db import models

from apps.core.models import AuditModel


class JobHalt(AuditModel):
    """
    A period during which work on a job was stopped.

    Deliberately a record rather than a status. Overwriting the job's work
    state with HALTED loses the stage it was in, so resuming depends on
    someone remembering — and a job put back into IN_PRODUCTION when it was
    actually in FINISHING gets remade from scratch.

    A job may be halted more than once over its life. Each occurrence is
    kept: three machine breakdowns in a month is a maintenance signal,
    repeated 'awaiting customer decision' against one customer is a
    commercial one. Halted time is also excluded from working time, which
    matters once wait times are estimated from history.
    """

    class Reason(models.TextChoices):
        MACHINE_BREAKDOWN = 'MACHINE_BREAKDOWN', 'Machine breakdown'
        MATERIALS_OUT     = 'MATERIALS_OUT',     'Materials unavailable'
        CUSTOMER_PAUSE    = 'CUSTOMER_PAUSE',    'Customer requested pause'
        AWAITING_CUSTOMER = 'AWAITING_CUSTOMER', 'Awaiting customer decision'
        QUALITY_FAILURE   = 'QUALITY_FAILURE',   'Quality failure'
        OTHER             = 'OTHER',             'Other'

    job = models.ForeignKey(
        'jobs.Job',
        on_delete    = models.CASCADE,
        related_name = 'halts',
    )

    reason = models.CharField(max_length=30, choices=Reason.choices)

    # Which machine, where a machine caused it. Set when a device is marked
    # down, so bringing it back resumes exactly the jobs it stopped —
    # matching on a note prefix would break silently the day the wording
    # changed. Null for halts with no machine behind them: materials out,
    # a customer pause, a quality failure.
    machine = models.ForeignKey(
        'production.Machine',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='halts_caused',
    )
    # Optional by design. A mandatory note becomes ritual — the same text
    # typed every time — and tells you less than the reason code alone.
    note = models.TextField(blank=True)

    # The stage the job was in when work stopped, so resuming restores it.
    work_state_at_halt = models.CharField(max_length=20)

    halted_at = models.DateTimeField(auto_now_add=True)
    halted_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'job_halts_raised',
    )

    resumed_at = models.DateTimeField(null=True, blank=True)
    resumed_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.SET_NULL,
        null         = True,
        blank        = True,
        related_name = 'job_halts_resumed',
    )

    class Meta:
        ordering            = ['-halted_at']
        verbose_name        = 'Job Halt'
        verbose_name_plural = 'Job Halts'
        indexes = [
            models.Index(fields=['job', 'resumed_at'], name='halt_job_resumed_idx'),
        ]

    def __str__(self):
        state = 'resumed' if self.resumed_at else 'active'
        return f'{self.job.job_number} — {self.get_reason_display()} ({state})'

    @property
    def is_active(self) -> bool:
        return self.resumed_at is None

    @property
    def duration(self):
        """How long work was stopped. None while still halted."""
        if not self.resumed_at:
            return None
        return self.resumed_at - self.halted_at