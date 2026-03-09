from django.db import models
from apps.core.models import AuditModel


class JobFile(AuditModel):
    """
    Files attached to a job — artwork, PDFs, references, design samples.
    """

    ORIGINAL = 'ORIGINAL'
    SAMPLE = 'SAMPLE'
    FINAL = 'FINAL'
    REFERENCE = 'REFERENCE'

    FILE_TYPE_CHOICES = [
        (ORIGINAL, 'Original File'),
        (SAMPLE, 'Design Sample'),
        (FINAL, 'Final File'),
        (REFERENCE, 'Reference'),
    ]

    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='files'
    )
    file = models.FileField(upload_to='jobs/%Y/%m/%d/')
    file_type = models.CharField(max_length=20, choices=FILE_TYPE_CHOICES, default=ORIGINAL)
    uploaded_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='uploaded_files'
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.job.job_number} — {self.file_type}"