"""
Reading what a file actually is.

A coordinator inspecting an arrival needs to know its dimensions, its
resolution and how many pages it has. Asking them to open every file in
another application to find out is how inspection becomes a formality that
gets skipped under pressure.

So the file is measured once, on upload, and the numbers travel with the
record.

These are measurements, not verdicts. Nothing here decides whether a file
is fit to print — that comparison needs a written specification standard
(minimum resolution, bleed, colour mode) which does not yet exist. Until it
does, the coordinator reads the numbers and judges. Encoding a guess at the
threshold now would make two coordinators disagree with each other through
the software rather than out loud.

Much of what arrives cannot be read at all: .cdr, .ai, .indd and .psd are
ordinary here and neither Pillow nor pypdf opens them. That is recorded as
UNSUPPORTED, which is a fact about the format, not a failure.
"""

import logging
import os
from decimal import Decimal

from apps.jobs.models import JobFile

logger = logging.getLogger(__name__)

# A PDF measures in points, 72 to the inch.
MM_PER_POINT = Decimal('25.4') / Decimal('72')

RASTER_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tif', '.tiff'}
PDF_EXTENSIONS = {'.pdf'}


def extract(job_file):
    """
    Measure a file and write what was found onto its record.

    Never raises. A file that cannot be read is still a file that belongs
    to a job, and an upload must not fail because the bytes were odd.
    Returns the JobFile, saved.
    """
    fields = ['metadata_state', 'original_filename', 'size_bytes', 'content_type']

    name = os.path.basename(job_file.file.name)
    job_file.original_filename = name
    ext = os.path.splitext(name)[1].lower()

    try:
        job_file.size_bytes = job_file.file.size
    except (OSError, ValueError):
        # The record can outlive the bytes — an ephemeral filesystem does
        # exactly this on every deploy.
        job_file.size_bytes = None

    try:
        if ext in PDF_EXTENSIONS:
            measured = _measure_pdf(job_file)
        elif ext in RASTER_EXTENSIONS:
            measured = _measure_raster(job_file)
        else:
            job_file.metadata_state = JobFile.UNSUPPORTED
            job_file.save(update_fields=fields)
            return job_file
    except Exception:
        # Deliberately broad. A corrupt, truncated or password-protected
        # file is a normal event at a print counter, and the upload it
        # arrived on must still succeed.
        logger.warning('Could not read file %s', job_file.pk, exc_info=True)
        job_file.metadata_state = JobFile.FAILED
        job_file.save(update_fields=fields)
        return job_file

    for key, value in measured.items():
        setattr(job_file, key, value)
        fields.append(key)

    job_file.metadata_state = JobFile.MEASURED
    job_file.save(update_fields=fields)
    return job_file


def _measure_pdf(job_file):
    from pypdf import PdfReader

    with job_file.file.open('rb') as handle:
        reader = PdfReader(handle)
        pages = len(reader.pages)
        box = reader.pages[0].mediabox

        # Page one stands for the document. A PDF with mixed page sizes
        # exists, but reporting the first is more useful than reporting
        # nothing, and the coordinator has the preview to catch the rest.
        width_mm = Decimal(str(float(box.width))) * MM_PER_POINT
        height_mm = Decimal(str(float(box.height))) * MM_PER_POINT

    return {
        'page_count': pages,
        'width_mm': width_mm.quantize(Decimal('0.01')),
        'height_mm': height_mm.quantize(Decimal('0.01')),
        'content_type': 'application/pdf',
        # A PDF has no inherent resolution. Its images do, but reaching
        # into them is a different job with a different failure mode, and
        # a wrong dpi is worse than an absent one.
    }


def _measure_raster(job_file):
    from PIL import Image

    with job_file.file.open('rb') as handle:
        with Image.open(handle) as img:
            width_px, height_px = img.size
            mode = img.mode
            fmt = img.format
            dpi_pair = img.info.get('dpi')

    dpi = None
    if dpi_pair:
        try:
            # The weaker axis is what prints badly, so it is the one kept.
            lower = min(float(dpi_pair[0]), float(dpi_pair[1]))
            # Some files declare a nonsense dpi of 0 or 1; treated as absent
            # rather than shown, because a false 1 dpi reads as alarming.
            if lower > 1:
                dpi = int(round(lower))
        except (TypeError, ValueError, IndexError):
            dpi = None

    result = {
        'width_px': width_px,
        'height_px': height_px,
        'colour_mode': _readable_mode(mode),
        'content_type': f'image/{fmt.lower()}' if fmt else '',
    }
    if dpi:
        result['dpi'] = dpi
        # Physical size only means something once resolution is known.
        result['width_mm'] = (Decimal(width_px) / Decimal(dpi) * Decimal('25.4')).quantize(Decimal('0.01'))
        result['height_mm'] = (Decimal(height_px) / Decimal(dpi) * Decimal('25.4')).quantize(Decimal('0.01'))

    return result


def _readable_mode(mode):
    """
    Pillow's mode strings are for programmers. A coordinator reads this.
    """
    return {
        'RGB': 'RGB', 'RGBA': 'RGB', 'RGBX': 'RGB',
        'CMYK': 'CMYK',
        'L': 'Grayscale', 'LA': 'Grayscale', '1': 'Grayscale',
        'P': 'Indexed',
        'YCbCr': 'RGB',
    }.get(mode, mode)