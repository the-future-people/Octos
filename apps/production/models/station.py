from django.db import models

from apps.core.models import AuditModel


class Station(AuditModel):
    """
    A kind of work — printing, laminating, binding, cutting, hand finishing.

    Company-wide rather than per-branch: printing is printing everywhere. A
    branch expresses itself through which machines it owns, not by
    redefining what the work is.

    Stations run independently. One job can print while another laminates,
    so this is a pipeline rather than a single queue — throughput is set by
    the busiest station, not the sum of all of them.
    """

    class Code(models.TextChoices):
        PRINT    = 'PRINT',    'Printing'
        LAMINATE = 'LAMINATE', 'Laminating'
        BIND     = 'BIND',     'Binding'
        CUT      = 'CUT',      'Cutting'
        FINISH   = 'FINISH',   'Hand finishing'

    code = models.CharField(
        max_length=20,
        choices=Code.choices,
        unique=True,
    )
    name = models.CharField(max_length=50)
    sequence = models.PositiveSmallIntegerField(
        help_text=(
            'Order work flows through. Printing comes before laminating, '
            'which comes before binding. Used to walk a job through the '
            'stations its services require.'
        ),
    )
    is_active = models.BooleanField(default=True)

    class Meta(AuditModel.Meta):
        ordering = ['sequence']
        verbose_name = 'Station'
        verbose_name_plural = 'Stations'

    def __str__(self) -> str:
        return self.name