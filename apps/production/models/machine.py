from django.db import models

from apps.core.models import AuditModel


class Machine(AuditModel):
    """
    A physical device at a branch.

    is_active is ownership; is_available is today. A machine sold or
    written off is inactive. A machine with a fault is unavailable — and
    that is what makes MACHINE_BREAKDOWN mean something. Until now it was a
    halt reason with no machine behind it, so nothing in the system knew
    the press was down.
    """

    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.PROTECT,
        related_name='machines',
    )
    machine_type = models.ForeignKey(
        'production.MachineType',
        on_delete=models.PROTECT,
        related_name='machines',
    )
    name = models.CharField(
        max_length=80,
        help_text='What the branch calls it, e.g. "Canon C5535i".',
    )
    model_number = models.CharField(
        max_length=120,
        blank=True,
        help_text='Manufacturer model, e.g. "imageRUNNER ADVANCE DX C5535i".',
    )
    serial_number = models.CharField(max_length=80, blank=True)

    is_active = models.BooleanField(
        default=True,
        help_text='Owned and in service. False once sold or written off.',
    )
    is_available = models.BooleanField(
        default=True,
        help_text=(
            'Running right now. False takes the machine out of scheduling '
            'and halts what is queued on it.'
        ),
    )
    unavailable_reason = models.CharField(
        max_length=200,
        blank=True,
        help_text='Why it is down, for whoever asks before it is fixed.',
    )
    unavailable_since = models.DateTimeField(null=True, blank=True)

    commissioned_on = models.DateField(
        null=True,
        blank=True,
        help_text='When it entered service. Useful once age and downtime correlate.',
    )
    notes = models.TextField(blank=True)

    class Meta(AuditModel.Meta):
        ordering = ['branch', 'machine_type__station__sequence', 'name']
        verbose_name = 'Machine'
        verbose_name_plural = 'Machines'
        indexes = [
            models.Index(
                fields=['branch', 'is_active', 'is_available'],
                name='machine_branch_state_idx',
            ),
        ]

    def __str__(self) -> str:
        state = '' if self.is_available else ' (down)'
        return f'{self.name} — {self.branch.code}{state}'

    @property
    def station(self):
        """The station this machine works at, via its type."""
        return self.machine_type.station

    @property
    def is_usable(self) -> bool:
        """Owned, in service, and running."""
        return self.is_active and self.is_available