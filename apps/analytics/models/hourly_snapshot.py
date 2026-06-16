from django.db import models


class HourlySheetSnapshot(models.Model):
    """
    Hourly breakdown of jobs and revenue for a closed DailySalesSheet.
    Populated by signal when a sheet closes.
    Used exclusively by PredictionEngine for historical pattern learning.

    One record per hour per sheet — hour 7 through 19.
    Never updated — immutable once created.
    """

    daily_sheet = models.ForeignKey(
        'finance.DailySalesSheet',
        on_delete=models.CASCADE,
        related_name='hourly_snapshots',
    )
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.CASCADE,
        related_name='hourly_snapshots',
    )
    date    = models.DateField(db_index=True)
    weekday = models.PositiveSmallIntegerField(
        db_index=True,
        help_text='0=Monday, 6=Sunday — denormalised for fast filtering',
    )
    week_of_month = models.PositiveSmallIntegerField(
        help_text='1–5 — which week of the month this date falls in',
    )
    hour = models.PositiveSmallIntegerField(
        help_text='Hour slot 7–19 (7am to 7pm)',
    )

    # ── Job metrics ───────────────────────────────────────────
    job_count     = models.PositiveIntegerField(default=0)
    revenue       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    avg_job_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Weather at time of snapshot ───────────────────────────
    weather_condition = models.CharField(
        max_length=30, blank=True,
        help_text='clear | cloudy | light_rain | heavy_rain | harmattan',
    )
    precipitation_mm = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text='Actual precipitation for this hour in mm',
    )

    class Meta:
        ordering        = ['date', 'hour']
        unique_together = [['daily_sheet', 'hour']]
        indexes         = [
            models.Index(fields=['branch', 'weekday', 'hour']),
            models.Index(fields=['branch', 'date']),
        ]
        verbose_name        = 'Hourly Sheet Snapshot'
        verbose_name_plural = 'Hourly Sheet Snapshots'

    def __str__(self):
        return f'{self.branch.code} | {self.date} | {self.hour:02d}:00'

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError('HourlySheetSnapshot records are immutable.')
        super().save(*args, **kwargs)