from django.db import models

from apps.core.models import AuditModel


class ServiceStation(AuditModel):
    """
    The route a service takes through the stations, and what it costs in
    time at each.

    A4 binding needs the press and then the binder, so it has two rows. A4
    printing needs only the press, so it has one. Typing needs a person and
    no machine at all, so its machine_type is null.

    Two time figures, not one. Five hundred flyers is not five times a
    hundred flyers — setup is paid once per job and running is marginal per
    unit. A single "minutes per job" number cannot express that and would
    misprice every large order.

    These figures are the seed, not the truth. StationTiming carries what
    each branch actually achieves, so a new branch quotes sensibly on day
    one and diverges as real work flows through.
    """

    service = models.ForeignKey(
        'jobs.Service',
        on_delete=models.CASCADE,
        related_name='station_routes',
    )
    station = models.ForeignKey(
        'production.Station',
        on_delete=models.PROTECT,
        related_name='service_routes',
    )
    machine_type = models.ForeignKey(
        'production.MachineType',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='service_routes',
        help_text=(
            'The class of device this step needs. Null where the work is '
            'done by hand — a branch with no such machine cannot take the '
            'job, and RoutingEngine sends it somewhere that can.'
        ),
    )
    sequence = models.PositiveSmallIntegerField(
        default=1,
        help_text='Order within this service. Print before bind.',
    )

    setup_minutes = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        help_text='Fixed cost per job — plate, settings, loading stock.',
    )
    minutes_per_unit = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=0,
        help_text='Marginal cost per unit once running.',
    )

    class Meta(AuditModel.Meta):
        ordering = ['service', 'sequence']
        verbose_name = 'Service Station'
        verbose_name_plural = 'Service Stations'
        constraints = [
            models.UniqueConstraint(
                fields=['service', 'station'],
                name='unique_service_station',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.service.name} → {self.station.name}'

    def estimated_minutes(self, quantity: int = 1) -> float:
        """
        Seed estimate for this step at this quantity. Ignores the queue and
        the branch — the caller applies both.
        """
        return float(self.setup_minutes) + float(self.minutes_per_unit) * quantity