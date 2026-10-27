from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import AuditModel


class MachineOperator(AuditModel):
    """
    A person assigned to run a machine.

    A record, not a field on the machine: who ran the 10ft in March stays
    answerable after they move to UV. An assignment is current while
    active_until is empty; ending it closes the record rather than
    deleting it.

    A machine may have several current operators (one to three per
    machine, by load), and a person may hold several machines at once:
    the DTF printer and the heat press are one person's work. A machine
    with at least one current operator is staffed, and on a staffed
    machine work starts only on the operator's Start.
    """

    operator = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='machine_assignments',
    )
    machine = models.ForeignKey(
        'production.Machine',
        on_delete=models.PROTECT,
        related_name='operator_assignments',
    )
    active_from  = models.DateTimeField(default=timezone.now)
    active_until = models.DateTimeField(
        null=True, blank=True,
        help_text='Empty while the assignment stands.',
    )

    class Meta(AuditModel.Meta):
        ordering = ['machine', '-active_from']
        verbose_name = 'Machine Operator'
        verbose_name_plural = 'Machine Operators'
        constraints = [
            models.UniqueConstraint(
                fields=['operator', 'machine'],
                condition=Q(active_until__isnull=True),
                name='machine_operator_one_current',
            ),
        ]
        indexes = [
            models.Index(fields=['machine', 'active_until'], name='machine_operator_current_idx'),
        ]

    def __str__(self) -> str:
        state = '' if self.active_until is None else ' (ended)'
        return f'{self.operator} on {self.machine.name}{state}'

    @property
    def is_current(self) -> bool:
        return self.active_until is None