from django.db import models

from apps.core.models import AuditModel


class StationTiming(AuditModel):
    """
    What work actually takes at a station, at a branch, at a given hour on
    a given day.

    Per branch because different people work at different branches and the
    same job genuinely takes longer in some places than others. Seeded from
    the service-level figure so a new branch quotes sensibly on day one,
    then corrected as real jobs flow through.

    Measured at the station, never at the person. A per-person productivity
    figure would be wrong often — a slow afternoon is usually one difficult
    job, not a slow worker — and it would be acted on as though it were
    right. Worse, measuring throughput rewards rushing finishing, which is
    the exact quality this business intends to compete on. Station timings
    answer the scheduling question without attaching a number to a name. A
    person genuinely struggling shows up as a station running slow, and a
    manager looks into it with context rather than through a metric.
    """

    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.CASCADE,
        related_name='station_timings',
    )
    station = models.ForeignKey(
        'production.Station',
        on_delete=models.CASCADE,
        related_name='timings',
    )

    hour_of_day = models.PositiveSmallIntegerField(
        help_text='0–23, local time. A busy afternoon is not a quiet morning.',
    )
    day_of_week = models.PositiveSmallIntegerField(
        help_text='0 = Monday through 5 = Saturday. The week runs Mon–Sat.',
    )

    observed_minutes_per_unit = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        help_text='Rolling average of what this station actually achieves here.',
    )
    correction_factor = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=1,
        help_text=(
            'Measured over predicted. Absorbs everything the model does '
            'not represent — machine contention, hand finishing, breaks, '
            'interruptions — without pretending to model any of it. Above '
            'one means the branch runs slower here than the seed figure.'
        ),
    )
    sample_count = models.PositiveIntegerField(
        default=0,
        help_text=(
            'Observations behind these figures. Low counts should not be '
            'quoted to a customer — a number the branch cannot hit is '
            'worse than no number.'
        ),
    )
    last_observed_at = models.DateTimeField(null=True, blank=True)

    class Meta(AuditModel.Meta):
        ordering = ['branch', 'station', 'day_of_week', 'hour_of_day']
        verbose_name = 'Station Timing'
        verbose_name_plural = 'Station Timings'
        constraints = [
            models.UniqueConstraint(
                fields=['branch', 'station', 'day_of_week', 'hour_of_day'],
                name='unique_station_timing_slot',
            ),
        ]
        indexes = [
            models.Index(
                fields=['branch', 'station'],
                name='timing_branch_station_idx',
            ),
        ]

    def __str__(self) -> str:
        return (
            f'{self.branch.code} · {self.station.name} · '
            f'day {self.day_of_week} hour {self.hour_of_day}'
        )

    @property
    def is_reliable(self) -> bool:
        """
        Enough observations to quote. The threshold is a starting guess and
        should move once there is real data to judge it against.
        """
        return self.sample_count >= 20