"""
Every time Octos moved a job's promise, and why.

The first promise lives on the job and is never changed except when the
customer changes the job; this is the history in between. Nobody writes
one by hand: only the lateness check and a customer's change do.
"""

from django.db import models


class PromiseRevision(models.Model):
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='promise_revisions')
    from_at = models.DateTimeField(null=True, blank=True)
    to_at = models.DateTimeField()
    reason = models.CharField(max_length=100)
    customer_told = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.job_id}: {self.from_at} -> {self.to_at} ({self.reason})'