from django.db import models

from apps.core.models import AuditModel


class JobVerification(AuditModel):
    """
    A coordinator's check of a remote order before any work starts.

    A walk-in needs no verification: the customer is standing there and
    anything unclear is asked immediately. A remote order has nobody to
    ask, so someone opens the file, reads the spec, and decides whether it
    can be made as ordered.

    A record rather than a flag, for the same reason halts are records. A
    job can fail verification, go back to the customer, and be checked
    again once they send better artwork — a boolean holds only the last
    outcome, and loses both the history and the reason.

    The coordinator may call the customer to clarify a spec, on a company
    line and never a personal one. That call is recorded here: if a spec
    changes after a conversation, this is why, and a dispute weeks later
    has something to read.
    """

    class Outcome(models.TextChoices):
        PASSED           = 'PASSED',           'Cleared for production'
        ARTWORK_PROBLEM  = 'ARTWORK_PROBLEM',  'Artwork not usable'
        SPEC_UNCLEAR     = 'SPEC_UNCLEAR',     'Specification unclear'
        SPEC_IMPOSSIBLE  = 'SPEC_IMPOSSIBLE',  'Cannot be made as ordered'
        WRONG_FILE       = 'WRONG_FILE',       'Wrong or missing file'
        OTHER            = 'OTHER',            'Other'

    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='verifications',
    )
    outcome = models.CharField(
        max_length=20,
        choices=Outcome.choices,
    )
    note = models.TextField(
        blank=True,
        help_text=(
            'What was found. Optional on a pass, since there is usually '
            'nothing to say; a mandatory note becomes ritual.'
        ),
    )

    customer_contacted = models.BooleanField(
        default=False,
        help_text='Whether the customer was called or messaged about this.',
    )
    customer_response = models.TextField(
        blank=True,
        help_text='What the customer said, in the words of whoever spoke to them.',
    )

    checked_at = models.DateTimeField(auto_now_add=True)
    checked_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='job_verifications',
    )

    class Meta(AuditModel.Meta):
        ordering = ['-checked_at']
        verbose_name = 'Job Verification'
        verbose_name_plural = 'Job Verifications'
        indexes = [
            models.Index(
                fields=['job', 'outcome'],
                name='verification_job_outcome_idx',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.job.job_number} — {self.get_outcome_display()}'

    @property
    def passed(self) -> bool:
        return self.outcome == self.Outcome.PASSED