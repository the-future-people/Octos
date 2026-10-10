"""
Artwork held while the customer decides.

A file has to be judged before anything is committed — that is the only
moment a warning does any good. But judging means reading the bytes,
and making the customer send them twice is the worst thing we could ask
of someone on mobile data: a 30MB banner uploaded once to be checked
and again to be ordered is the likeliest point of abandonment in the
whole flow.

So the check keeps the file here, and the commit moves it onto the
order. Nothing about this row belongs to a customer or an order yet.

It lives in its own table rather than as an OrderFile with no order,
for the same reason an online order is not a Job with no branch: a
half-formed thing in the table the real ones live in means every query
has to remember to exclude it, and one day one of them will not.

Swept after a couple of hours. Most of these are abandoned, which is
the point — a customer who checks a file and changes their mind should
cost us nothing but the sweep.
"""

from django.db import models
from django.utils import timezone

from apps.core.models import AuditModel


# The verdict token is good for an hour. The file outlasts it, so a
# commit at the fifty-ninth minute still finds something to copy.
STAGED_LIFETIME_HOURS = 2


class StagedUpload(AuditModel):
    file = models.FileField(upload_to='staged/%Y/%m/%d/')

    original_filename = models.CharField(max_length=255, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=100, blank=True)

    # What makes this file this file. The signed verdict carries it, so
    # a staged row swapped for another cannot be passed off as the one
    # that was judged.
    file_hash = models.CharField(max_length=64, db_index=True)

    # ── What the measuring found ──────────────────────────────────
    # Copied onto the OrderFile at commit rather than measured again:
    # the verdict the customer was shown was based on these, and
    # re-reading the file could only produce a different answer.
    metadata_state = models.CharField(max_length=20, blank=True)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    width_px = models.PositiveIntegerField(null=True, blank=True)
    height_px = models.PositiveIntegerField(null=True, blank=True)
    width_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    height_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    dpi = models.PositiveIntegerField(null=True, blank=True)
    colour_mode = models.CharField(max_length=20, blank=True)
    pdf_images = models.JSONField(default=list, blank=True)

    # ── What it was judged to be ──────────────────────────────────
    verdict = models.CharField(max_length=10, blank=True)
    checks = models.JSONField(default=list, blank=True)

    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.original_filename} ({self.verdict})'

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(
                hours=STAGED_LIFETIME_HOURS,
            )
        super().save(*args, **kwargs)

    @property
    def is_live(self):
        return self.expires_at > timezone.now()

    def measured(self):
        """
        What the measuring found, as the fields an OrderFile carries.

        Used to copy this across at commit without reading the file
        again — the customer was shown a verdict based on these, and
        the stored record should say the same thing.
        """
        return {
            'metadata_state': self.metadata_state,
            'page_count': self.page_count,
            'width_px': self.width_px,
            'height_px': self.height_px,
            'width_mm': self.width_mm,
            'height_mm': self.height_mm,
            'dpi': self.dpi,
            'colour_mode': self.colour_mode,
            'pdf_images': self.pdf_images,
        }