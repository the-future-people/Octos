from django.db import models

from apps.core.models import AuditModel


class JobSpecChange(AuditModel):
    """
    One change to one field of one line, made during inspection after
    the customer agreed to it.

    The coordinator may correct a specification (a size, a material, a
    finish) when it is critical and only once the customer has confirmed
    on the recorded company line. The price never moves: what was paid
    for is what is owed. A quantity is not a specification; changing it
    changes the money and goes back through the counter.

    One row per field changed, so a dispute weeks later can read exactly
    what the order said, what it says now, who changed it, and what the
    customer said that made it right to.
    """

    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='spec_changes',
    )
    line_item = models.ForeignKey(
        'jobs.JobLineItem',
        on_delete=models.CASCADE,
        related_name='spec_changes',
    )
    field = models.CharField(max_length=60)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)

    customer_response = models.TextField(
        help_text='What the customer agreed to, in the words of whoever spoke to them.',
    )

    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='job_spec_changes',
    )

    class Meta(AuditModel.Meta):
        ordering = ['changed_at']
        verbose_name = 'Job Specification Change'
        verbose_name_plural = 'Job Specification Changes'

    def __str__(self) -> str:
        return f'{self.job.job_number} — {self.field}: {self.old_value} → {self.new_value}'