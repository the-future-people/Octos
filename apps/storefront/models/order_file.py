"""
Artwork sent before there is a job to attach it to.

JobFile requires a job, and a job does not exist until payment and
routing have settled. A nullable job on that table would mean the
coordinator's queries had to exclude half-formed things on every read —
the same reason an online order is not a Job with a null branch.

So the file lives here and is copied across at conversion.

The verdicts are stored, not recomputed on every read. They are a
judgement about a file *and* the size it was ordered at, so they go
stale when the order changes — which is why the order's own view
rejudges rather than trusting what is here.
"""

from django.db import models

from apps.core.models import AuditModel


class OrderFile(AuditModel):
    order = models.ForeignKey(
        'storefront.OnlineOrder',
        on_delete=models.CASCADE,
        related_name='files',
    )

    line_id = models.CharField(
        max_length=36, blank=True, db_index=True,
        help_text=(
            'Which line of the order this artwork belongs to. An order '
            'can hold a banner, flyers and programmes at once, and the '
            "banner's file is not the flyer's — so a file belongs to a "
            'line rather than to the order as a whole.'
        ),
    )

    file = models.FileField(upload_to='storefront/%Y/%m/%d/')
    original_filename = models.CharField(max_length=255, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=100, blank=True)

    # ── Measured on upload ────────────────────────────────────────
    # The same fields JobFile carries, so conversion is a copy rather
    # than a re-measurement.
    metadata_state = models.CharField(max_length=20, blank=True)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    width_px = models.PositiveIntegerField(null=True, blank=True)
    height_px = models.PositiveIntegerField(null=True, blank=True)
    width_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    height_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    dpi = models.PositiveIntegerField(null=True, blank=True)
    colour_mode = models.CharField(max_length=20, blank=True)
    pdf_images = models.JSONField(default=list, blank=True)

    # ── Judged ────────────────────────────────────────────────────
    verdict = models.CharField(max_length=10, blank=True)
    checks = models.JSONField(default=list, blank=True)

    # A warning proceeds, and the acceptance is recorded — so the
    # coordinator can see the customer was told rather than discovering
    # the problem himself.
    warning_accepted = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order.order_number} — {self.original_filename}"