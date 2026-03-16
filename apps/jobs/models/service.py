from django.db import models
from apps.core.models import AuditModel


class Service(AuditModel):
    """
    A service offered by Farhat Printing Press.
    spec_template drives the dynamic intake form in the New Job modal.
    """

    # Categories map to job types
    INSTANT    = 'INSTANT'
    PRODUCTION = 'PRODUCTION'
    DESIGN     = 'DESIGN'

    CATEGORY_CHOICES = [
        (INSTANT,    'Instant'),
        (PRODUCTION, 'Production'),
        (DESIGN,     'Design'),
    ]

    UNIT_CHOICES = [
        ('PER_COPY',  'Per Copy'),
        ('PER_PIECE', 'Per Piece'),
        ('PER_SQFT',  'Per Sq Ft'),
        ('PER_SQCM',  'Per Sq Cm'),
        ('PER_JOB',   'Per Job'),
    ]

    name                 = models.CharField(max_length=100, unique=True)
    code                 = models.CharField(max_length=20, unique=True)
    category             = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    unit                 = models.CharField(max_length=20, choices=UNIT_CHOICES, default='PER_PIECE')
    description          = models.TextField(blank=True)
    requires_design      = models.BooleanField(default=False)
    requires_file_upload = models.BooleanField(default=False)
    is_active            = models.BooleanField(default=True)

    # ── Dynamic spec template ────────────────────────────────────
    # Defines which fields the New Job modal renders for this service.
    # Each entry is a field descriptor:
    #
    # {
    #   "key":      "width_cm",           # stored in Job.specifications
    #   "label":    "Width (cm)",          # shown in the form
    #   "type":     "number"|"select"|"text"|"checkbox",
    #   "required": true|false,
    #   "options":  ["Vinyl","Canvas"],    # only for type=select
    #   "default":  "Vinyl",              # optional default value
    #   "min":      1,                    # optional, for number fields
    #   "max":      1000,                 # optional, for number fields
    #   "unit":     "cm",                 # optional display suffix
    # }
    #
    # Seeded templates:
    #
    # Photocopy (INSTANT):
    #   quantity, pages, color (select: B&W/Color), sides (select: Single/Double)
    #
    # ID Card Printing (INSTANT):
    #   quantity, sides (select: Single/Double)
    #
    # Banner Printing (PRODUCTION):
    #   width_cm, height_cm, material (select: Vinyl/Canvas/Mesh),
    #   finishing (select: Hemmed/Eyelets/None)
    #
    # Business Cards (PRODUCTION):
    #   quantity, size (select: Standard/Square/Mini),
    #   paper_stock (select: Matte/Glossy/Kraft), sides (select: Single/Double)
    #
    # Logo Design (DESIGN):
    #   style (select: Modern/Minimalist/Classic/Playful),
    #   color_preference (text), notes (text)
    #
    # ── Smart defaults ───────────────────────────────────────────
    # Pre-filled configuration derived from the service name.
    # Used by the POS modal to skip manual field entry for known services.
    #
    # Example for "A4 B&W Photocopy 1-sided":
    # {
    #   "paper_size": "A4",
    #   "is_color":   false,
    #   "sides":      "SINGLE",
    #   "pages":      1,
    #   "sets":       1
    # }
    smart_defaults = models.JSONField(
        default=dict,
        blank=True,
        help_text='Pre-filled defaults for POS modal. Derived from service name.',
    )
    spec_template = models.JSONField(
        default=list,
        blank=True,
        help_text='Field definitions for the dynamic intake form. See model docstring.',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.category})"