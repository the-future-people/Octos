from django.db import models


class BranchSnapshot(models.Model):
    """
    Daily aggregate snapshot of a branch's operational metrics.
    Created by analytics.services.compute_snapshot().
    Run daily via Celery beat task.

    This is a pre-computed cache of branch health — not a source of truth.
    The source of truth is always the operational models in finance and jobs.
    """

    branch = models.ForeignKey(
        'organization.Branch',
        on_delete    = models.CASCADE,
        related_name = 'snapshots',
    )
    date = models.DateField(db_index=True)

    # ── Job metrics ───────────────────────────────────────────
    total_jobs       = models.PositiveIntegerField(default=0)
    pending_jobs     = models.PositiveIntegerField(default=0)
    in_progress_jobs = models.PositiveIntegerField(default=0)
    completed_jobs   = models.PositiveIntegerField(default=0)
    cancelled_jobs   = models.PositiveIntegerField(default=0)
    routed_out_jobs  = models.PositiveIntegerField(default=0)

    # ── Revenue metrics ───────────────────────────────────────
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    avg_job_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Communication metrics ─────────────────────────────────
    total_conversations    = models.PositiveIntegerField(default=0)
    unread_conversations   = models.PositiveIntegerField(default=0)
    resolved_conversations = models.PositiveIntegerField(default=0)

    # ── Load ──────────────────────────────────────────────────
    load_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    snapshot_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering        = ['-date']
        unique_together = [['branch', 'date']]
        indexes         = [
            models.Index(fields=['branch', 'date']),
        ]
        verbose_name        = 'Branch Snapshot'
        verbose_name_plural = 'Branch Snapshots'

    def __str__(self):
        return f'{self.branch} | {self.date}'

    @property
    def completion_rate(self):
        if self.total_jobs == 0:
            return 0
        return round((self.completed_jobs / self.total_jobs) * 100, 1)