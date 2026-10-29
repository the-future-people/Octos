from django.db import models

from apps.core.models import AuditModel


class JobStep(AuditModel):
    """
    One station one line passes through, on one machine or by hand.

    A line's route (ServiceStation, in sequence) becomes its steps when the
    job is cleared: print on the 10ft, then cut by hand, then eyelets. Each
    line has its own, so a banner and its stickers run on different machines
    at once.

    A machine's queue is its steps that are not done: the one ACTIVE (being
    worked now) first, then the WAITING ones by slack, the least first.
    Slack is the job's promise less the work still left on the line.
    reached_at records when a step came to the front. On a machine with no
    operator assigned it goes straight on, as before. On a staffed machine
    it waits there for the operator's Start, which is when the work really
    began (started_at). Marking it DONE moves the line to its next step and
    the next job up. Every line ends at the bench, so an operator's Done
    always frees the machine and the final check happens at finishing.

    by_hand is decided by the route, not the station: a route step naming
    no machine type is done by hand at that station's bench, even where the
    station has machines for other work. Cutting a banner is by hand though
    the cutting station also has a plotter.

    A step with no machine that is not by hand is unassigned: nothing that
    fits was up, or the branch has no such machine. The coordinator places
    it, or marks it done when it was done another way.

    The customer never sees steps. Their stage follows: every print step
    done means Finishing; every step done means ready for the check.

    expected_minutes is the work itself, worked out when the step is made,
    from measured timings where Octos has them and seed figures where not.
    reached_at and done_at are what actually happened, which is what the
    timing service learns from.
    """

    class State(models.TextChoices):
        WAITING = 'WAITING', 'Waiting'
        ACTIVE  = 'ACTIVE',  'On the machine'
        DONE    = 'DONE',    'Done'

    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='steps',
    )
    line_item = models.ForeignKey(
        'jobs.JobLineItem',
        on_delete=models.CASCADE,
        related_name='steps',
    )
    station = models.ForeignKey(
        'production.Station',
        on_delete=models.PROTECT,
        related_name='job_steps',
    )
    machine = models.ForeignKey(
        'production.Machine',
        on_delete=models.SET_NULL,
        related_name='job_steps',
        null=True,
        blank=True,
        help_text='Empty for work done by hand, or where nothing fitted and the coordinator must place it.',
    )
    by_hand = models.BooleanField(
        default=False,
        help_text="Worked at the station's bench: the route names no machine type for this step.",
    )
    sequence = models.PositiveSmallIntegerField(
        help_text='Order within the line, from the route.',
    )
    state = models.CharField(
        max_length=10,
        choices=State.choices,
        default=State.WAITING,
        db_index=True,
    )
    expected_minutes = models.DecimalField(
        max_digits=8,
        decimal_places=1,
        default=0,
    )

    reached_at = models.DateTimeField(null=True, blank=True)
    done_at    = models.DateTimeField(null=True, blank=True)
    done_by    = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        related_name='job_steps_done',
        null=True,
        blank=True,
    )

    # The operator's Start on a staffed machine: when the work really
    # began, as opposed to when the step reached the front (reached_at).
    started_at = models.DateTimeField(null=True, blank=True)
    started_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        related_name='job_steps_started',
        null=True,
        blank=True,
    )
    # What the operator reported at Done. Spoilt pieces are waste until
    # the coordinator confirms them for a reprint.
    quantity_made   = models.PositiveIntegerField(null=True, blank=True)
    quantity_spoilt = models.PositiveIntegerField(null=True, blank=True)
    # On a staffed machine Done is the operator's. When someone else has
    # to close it (the operator left with it running), why, in their
    # words; done_by then names them, not the operator.
    done_override = models.CharField(max_length=200, blank=True, default='')

    class Meta(AuditModel.Meta):
        ordering = ['line_item_id', 'sequence']
        verbose_name = 'Job Step'
        verbose_name_plural = 'Job Steps'
        constraints = [
            models.UniqueConstraint(
                fields=['line_item', 'station'],
                name='job_step_one_per_line_station',
            ),
        ]
        indexes = [
            models.Index(fields=['machine', 'state'], name='job_step_machine_state_idx'),
            models.Index(fields=['job', 'state'], name='job_step_job_state_idx'),
        ]

    def __str__(self) -> str:
        where = self.machine.name if self.machine_id else ('bench' if self.by_hand else 'unassigned')
        return f'{self.job.job_number} — {self.station.code} on {where} ({self.state})'