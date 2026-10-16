from django.db import models

from apps.core.models import AuditModel


class FinalCheck(AuditModel):
    """
    The last look at a piece before it is handed to a customer: what was
    ordered against what was made.

    Taken at each line's last step, whatever that is: the bench for a
    banner, the plotter for a sticker. A piece that matches is ready, and
    once every piece of the job is, the customer is told. A piece that does
    not match is never handed over: it goes back to its machine to be made
    again, and the estimate grows by itself.

    Kept as a record, every one, so a customer saying "this is not what I
    ordered" weeks later can be answered with what was checked, by whom,
    when, and why it went round twice if it did.
    """

    class Outcome(models.TextChoices):
        PASSED    = 'PASSED',    'Matched, ready'
        SENT_BACK = 'SENT_BACK', 'Sent back to be made again'

    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='final_checks',
    )
    line_item = models.ForeignKey(
        'jobs.JobLineItem',
        on_delete=models.CASCADE,
        related_name='final_checks',
    )
    step = models.ForeignKey(
        'jobs.JobStep',
        on_delete=models.SET_NULL,
        related_name='final_checks',
        null=True,
        blank=True,
    )
    outcome = models.CharField(max_length=12, choices=Outcome.choices)
    rows = models.JSONField(
        default=list,
        help_text='Each row: field, label, ordered, made, match.',
    )
    promised_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    checked_at = models.DateTimeField(auto_now_add=True)
    checked_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='final_checks',
    )

    class Meta(AuditModel.Meta):
        ordering = ['-checked_at']
        verbose_name = 'Final Check'
        verbose_name_plural = 'Final Checks'

    def __str__(self) -> str:
        return f'{self.job.job_number} — {self.get_outcome_display()}'