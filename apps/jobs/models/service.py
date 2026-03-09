from django.db import models
from apps.core.models import AuditModel


class Service(AuditModel):
    """
    Represents a service offered by Farhat Printing Press.
    Services are company-wide — branches then select which ones they offer.
    e.g. Photocopy, Large Format Print, Binding, Lamination, Design
    """

    # Service Categories
    INSTANT = 'INSTANT'
    PRODUCTION = 'PRODUCTION'
    DESIGN = 'DESIGN'

    CATEGORY_CHOICES = [
        (INSTANT, 'Instant'),
        (PRODUCTION, 'Production'),
        (DESIGN, 'Design'),
    ]

    # Units
    PER_PAGE = 'PER_PAGE'
    PER_COPY = 'PER_COPY'
    PER_SQM = 'PER_SQM'
    PER_PIECE = 'PER_PIECE'
    PER_SET = 'PER_SET'
    FLAT_RATE = 'FLAT_RATE'

    UNIT_CHOICES = [
        (PER_PAGE, 'Per Page'),
        (PER_COPY, 'Per Copy'),
        (PER_SQM, 'Per Square Metre'),
        (PER_PIECE, 'Per Piece'),
        (PER_SET, 'Per Set'),
        (FLAT_RATE, 'Flat Rate'),
    ]

    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=20, unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES)
    description = models.TextField(blank=True)
    requires_design = models.BooleanField(default=False)
    requires_file_upload = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"