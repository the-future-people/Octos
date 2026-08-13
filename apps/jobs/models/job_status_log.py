from django.db import models
from apps.core.models import AuditModel


class JobStatusLog(AuditModel):
    """
    Immutable log of every job status transition.
    Every state change is recorded — who, when, why, from where, to where.
    This is the audit trail for the entire job lifecycle.
    """

    class Axis(models.TextChoices):
        PAYMENT  = 'PAYMENT',  'Payment'
        WORK     = 'WORK',     'Work'
        HANDOVER = 'HANDOVER', 'Handover'
        RECORD   = 'RECORD',   'Record'

    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='status_logs'
    )
    axis = models.CharField(
        max_length=10,
        choices=Axis.choices,
        default=Axis.RECORD,
        db_index=True,
        help_text=(
            'Which lifecycle axis this transition moved. RECORD covers '
            'draft/intake-held/cancellation, which are facts about the '
            'record rather than any axis, and is also what every '
            'pre-rebuild log row is backfilled to.'
        ),
    )
    from_status = models.CharField(max_length=30)
    to_status = models.CharField(max_length=30)
    actor = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='job_transitions'
    )
    notes = models.TextField(blank=True)
    transitioned_at = models.DateTimeField()

    class Meta:
        ordering = ['-transitioned_at']

    def __str__(self):
        return (
            f"{self.job.job_number} | {self.axis}: "
            f"{self.from_status} → {self.to_status} | "
            f"{self.actor} | {self.transitioned_at:%Y-%m-%d %H:%M}"
        )