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


# An image covering less than this share of the page is decoration — a
# corner logo, a rule, a watermark. It cannot be allowed to set the
# file's resolution, or artwork that prints perfectly would be refused
# over a small mark nobody looks at closely.
MEANINGFUL_AREA_SHARE = Decimal('0.05')


def _measure_pdf(job_file):
    from pypdf import PdfReader

    with job_file.file.open('rb') as handle:
        reader = PdfReader(handle)
        pages = len(reader.pages)
        page = reader.pages[0]
        box = page.mediabox

        # Page one stands for the document. A PDF with mixed page sizes
        # exists, but reporting the first is more useful than reporting
        # nothing, and the coordinator has the preview to catch the rest.
        width_pt = Decimal(str(float(box.width)))
        height_pt = Decimal(str(float(box.height)))
        width_mm = width_pt * MM_PER_POINT
        height_mm = height_pt * MM_PER_POINT

        images = _pdf_images(page, width_pt, height_pt)

    result = {
        'page_count': pages,
        'width_mm': width_mm.quantize(Decimal('0.01')),
        'height_mm': height_mm.quantize(Decimal('0.01')),
        'content_type': 'application/pdf',
        'pdf_images': images,
    }

    # The worst of the images big enough to matter. A page of vector art
    # has none, and says so by leaving dpi absent rather than inventing
    # a number for something that is infinitely sharp.
    meaningful = [i['dpi'] for i in images if i['meaningful'] and i['dpi']]
    if meaningful:
        result['dpi'] = min(meaningful)

    return result


def _pdf_images(page, page_width_pt, page_height_pt):
    """
    Every raster image drawn on the page, with the resolution it works
    out to where it sits.

    A PDF places an image through a transformation matrix: the pixels
    are one thing, the size it is drawn at is another, and the
    resolution is the first divided by the second. So a 300px logo is
    300dpi at one inch and 75dpi at four.

    The matrix is not on the image object — it lives in the page's
    instructions, so the page is walked and each draw is watched for.
    """
    page_area = float(page_width_pt) * float(page_height_pt)
    resources = page.get('/Resources', {})
    xobjects = resources.get('/XObject', {}) if resources else {}
    found = []

    def on_operator(operator, operands, cm, tm):
        if operator != b'Do' or not operands:
            return
        name = operands[0]
        try:
            xobject = xobjects[name].get_object()
        except (KeyError, TypeError, AttributeError):
            return
        if xobject.get('/Subtype') != '/Image':
            # A form, which may contain images of its own. Following it
            # needs the nested matrix too; left out rather than measured
            # wrongly.
            return

        px_w = xobject.get('/Width')
        px_h = xobject.get('/Height')
        if not px_w or not px_h:
            return

        # The matrix scales a unit square, so its first and fourth terms
        # are the drawn width and height in points.
        try:
            drawn_w_pt = abs(float(cm[0]))
            drawn_h_pt = abs(float(cm[3]))
        except (TypeError, ValueError, IndexError):
            return
        if not drawn_w_pt or not drawn_h_pt:
            return

        # The weaker axis is what prints badly, so it is the one kept —
        # the same rule the raster reader uses.
        dpi = int(round(min(
            px_w / (drawn_w_pt / 72.0),
            px_h / (drawn_h_pt / 72.0),
        )))
        share = (drawn_w_pt * drawn_h_pt) / page_area if page_area else 0

        found.append({
            'name': str(name),
            'width_px': int(px_w),
            'height_px': int(px_h),
            'drawn_mm': [
                round(drawn_w_pt * float(MM_PER_POINT), 1),
                round(drawn_h_pt * float(MM_PER_POINT), 1),
            ],
            'dpi': dpi,
            'page_share': round(share, 4),
            'meaningful': Decimal(str(share)) >= MEANINGFUL_AREA_SHARE,
        })

    page.extract_text(visitor_operand_before=on_operator)
    return found

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