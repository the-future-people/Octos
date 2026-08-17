from django.db import models

from apps.core.models import AuditModel


class MachineType(AuditModel):
    """
    A class of device — digital press, large format, laminator, binder.

    Capability is declared once per type rather than per physical device.
    Mapping every machine to every service it can run would be a large
    table maintained by hand and wrong the moment the catalogue changes;
    this way, buying a second press of a known type is one row, and it
    inherits every service that type can run.
    """

    class Code(models.TextChoices):
        DIGITAL_PRESS = 'DIGITAL_PRESS', 'Digital press'
        LARGE_FORMAT  = 'LARGE_FORMAT',  'Large format printer'
        LAMINATOR     = 'LAMINATOR',     'Laminator'
        BINDER        = 'BINDER',        'Binding machine'
        CUTTER        = 'CUTTER',        'Cutter'
        PLOTTER       = 'PLOTTER',       'Plotter'

    code = models.CharField(
        max_length=30,
        choices=Code.choices,
        unique=True,
    )
    name = models.CharField(max_length=60)
    station = models.ForeignKey(
        'production.Station',
        on_delete=models.PROTECT,
        related_name='machine_types',
        help_text='The station a device of this type works at.',
    )
    max_paper_size = models.CharField(
        max_length=10,
        blank=True,
        help_text=(
            'Largest sheet this class of device handles, e.g. A3. Blank '
            'where size is not the limit — a laminator and a press are '
            'constrained by different things.'
        ),
    )
    is_active = models.BooleanField(default=True)

    class Meta(AuditModel.Meta):
        ordering = ['station__sequence', 'name']
        verbose_name = 'Machine Type'
        verbose_name_plural = 'Machine Types'

    def __str__(self) -> str:
        return self.name