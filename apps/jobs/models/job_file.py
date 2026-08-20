from django.db import models
from apps.core.models import AuditModel


class JobFile(AuditModel):
    """
    Files attached to a job — artwork, PDFs, references, design samples.

    Carries measured facts about the file itself — dimensions, resolution,
    colour mode, page count — read once on upload. These are measurements,
    not judgements: nothing here decides whether a file is fit to print.
    That comparison needs a written specification standard, and until one
    exists the coordinator reads the numbers and decides.
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

    # ── Measured on upload ──────────────────────────────────────────
    # Every field nullable: a file that cannot be read still exists and
    # still belongs to its job.

    PENDING = 'PENDING'
    MEASURED = 'MEASURED'
    UNSUPPORTED = 'UNSUPPORTED'
    FAILED = 'FAILED'

    METADATA_STATE_CHOICES = [
        (PENDING, 'Not yet read'),
        (MEASURED, 'Measured'),
        (UNSUPPORTED, 'Format not readable'),
        (FAILED, 'Could not be read'),
    ]

    metadata_state = models.CharField(
        max_length=20,
        choices=METADATA_STATE_CHOICES,
        default=PENDING,
        help_text="Distinguishes a file never read from one read without result."
    )
    original_filename = models.CharField(max_length=255, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=100, blank=True)

    page_count = models.PositiveIntegerField(null=True, blank=True)

    # Raster files carry pixels; PDFs do not. Both are kept rather than
    # converted, because a conversion needs a dpi that is often absent.
    width_px = models.PositiveIntegerField(null=True, blank=True)
    height_px = models.PositiveIntegerField(null=True, blank=True)
    width_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    height_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    dpi = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Lower of horizontal and vertical, as the weaker axis is what prints badly."
    )
    colour_mode = models.CharField(
        max_length=20, blank=True,
        help_text="As declared by the file — RGB, CMYK, Grayscale."
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.job.job_number} — {self.file_type}"