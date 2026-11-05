"""
Judging a customer's file against what they ordered: one place, for the
storefront's upload and for files customers send Octos on WhatsApp.

A file is never judged alone. measure() reads it (pixels, physical size,
dpi, pages, colour mode); check_file() compares that with the order line
(width and height in inches, pages). A 300 dpi photo is fine on an A4
flyer and soft on a 3 x 6 ft banner. A refused file is never kept; any
other is staged with its verdict, ready to attach to an order.

Moved out of the storefront's upload view (Nov 2026), which now calls it.
"""
from django.core.files.uploadedfile import SimpleUploadedFile

# What a staged file records from the measuring, for the floor to see.
STAGED_FIELDS = (
    'metadata_state', 'page_count', 'width_px', 'height_px',
    'width_mm', 'height_mm', 'dpi', 'colour_mode', 'pdf_images',
)


class _Carrier:
    """Something with a .file, which is all measure() wants."""

    def __init__(self, upload):
        self.file = upload


def inspect_file(content, name, content_type, specs):
    """
    Measure and judge a file against an order line's specifications.
    Returns (file hash, what was measured, the verdict, the StagedUpload
    or None when the file is refused).
    """
    from apps.jobs.services.file_checks import check_file
    from apps.jobs.services.file_metadata import measure
    from apps.storefront.models import StagedUpload
    from apps.storefront.services.verdicts import file_hash

    # The bytes are needed three times (hashed, measured, stored); each
    # read gets its own fresh file over the same bytes.
    def rewound():
        return SimpleUploadedFile(name, content, content_type=content_type)

    upload_hash = file_hash(rewound())

    # The same measuring the counter uses. Two implementations of
    # "how many dots per inch is this" would eventually disagree,
    # and a customer would get different answers about one file.
    found = measure(_Carrier(rewound()))

    verdict = check_file(
        metadata_state=found.get('metadata_state'),
        content_type=content_type or '',
        width_px=found.get('width_px'),
        height_px=found.get('height_px'),
        width_mm=found.get('width_mm'),
        height_mm=found.get('height_mm'),
        page_count=found.get('page_count'),
        colour_mode=found.get('colour_mode'),
        pdf_images=found.get('pdf_images'),
        ordered_width_in=specs.get('width_in'),
        ordered_height_in=specs.get('height_in'),
        ordered_pages=specs.get('pages'),
    )

    staged = None
    if verdict['verdict'] != 'refuse':
        staged = StagedUpload.objects.create(
            file=rewound(),
            original_filename=name,
            size_bytes=len(content),
            content_type=content_type or '',
            file_hash=upload_hash,
            verdict=verdict['verdict'],
            checks=verdict['checks'],
            **{k: v for k, v in found.items() if k in STAGED_FIELDS},
        )
    return upload_hash, found, verdict, staged