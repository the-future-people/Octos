"""
Files customers send on WhatsApp, kept before WhatsApp deletes them.

Meta holds media for about 30 days and gives it out only through a
short-lived address. So as soon as a media message is recorded, the
worker fetches it: one call turns the media id into an address, a second
downloads the bytes (both need the access token). The file goes into
default storage (R2 in production, private, signed links only) with its
type, size and, for a PDF, its page count, which Octos prices by.

Fields are written with an update, not Message.save(): save also moves
the conversation's preview line, and a file arriving late must never
replace a newer message's preview.
"""
import io
import logging
import mimetypes
import os

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from django.utils.text import get_valid_filename

from apps.communications.models import Message
from apps.communications.services.whatsapp_client import API_VERSION, TIMEOUT

logger = logging.getLogger(__name__)

MAX_BYTES = 100 * 1024 * 1024  # WhatsApp's own ceiling for a document


class MediaError(Exception):
    """A file that can't be fetched and won't be by trying again (gone, too big)."""


def fetch(message_id):
    """Download and keep the file behind one message. Returns the message."""
    message = Message.objects.get(pk=message_id)
    if message.media_file or not message.media_id:
        return message  # already kept, or nothing to keep

    content, mime = download(message.media_id)
    mime = message.media_mime or mime
    name = _file_name(message, mime)
    # A Word file is kept as the PDF it becomes: that is what Octos counts,
    # the customer is quoted for and the floor prints (7 Nov 2026).
    converted_from = ''
    from apps.jobs.services.word_to_pdf import ConversionFailed, is_word, pdf_name, to_pdf
    if is_word(name, mime):
        try:
            content = to_pdf(content, name)
            converted_from = 'Word'
            name, mime = pdf_name(name), 'application/pdf'
        except ConversionFailed:
            logger.warning('Could not convert %s to PDF', name, exc_info=True)
    path = default_storage.save(
        f'communications/media/{timezone.now():%Y/%m}/{name}', ContentFile(content),
    )
    info = describe(content, name, mime)
    if converted_from:
        info['converted_from'] = converted_from
    Message.objects.filter(pk=message.pk).update(
        media_file=path, media_mime=mime, media_size=len(content),
        media_name=name if converted_from else message.media_name,
        media_pages=info.get('page_count') or count_pages(content, mime),
        media_info=info,
    )
    message.refresh_from_db()
    logger.info('Kept WhatsApp media for message %s: %s, %s bytes', message.pk, path, len(content))
    return message


def download(media_id):
    """(bytes, mime type) for a WhatsApp media id. Network errors raise requests' own."""
    token = settings.WHATSAPP_ACCESS_TOKEN
    if not token:
        raise ImproperlyConfigured('WHATSAPP_ACCESS_TOKEN is not set.')
    headers = {'Authorization': f'Bearer {token}'}

    meta = requests.get(f'https://graph.facebook.com/{API_VERSION}/{media_id}',
                        headers=headers, timeout=TIMEOUT)
    if meta.status_code in (400, 404):
        raise MediaError(f'media {media_id} is gone ({meta.status_code})')
    meta.raise_for_status()
    info = meta.json()
    if int(info.get('file_size') or 0) > MAX_BYTES:
        raise MediaError(f"media {media_id} is {info.get('file_size')} bytes, over the limit")

    body = requests.get(info['url'], headers=headers, timeout=TIMEOUT * 3)
    body.raise_for_status()
    return body.content, info.get('mime_type', '')


def count_pages(content, mime):
    """Pages in a PDF, 1 for an image, None when it can't be told."""
    if mime == 'application/pdf':
        try:
            from pypdf import PdfReader
            return len(PdfReader(io.BytesIO(content)).pages)
        except Exception:
            logger.warning('Could not count the pages of a PDF', exc_info=True)
            return None
    if mime.startswith('image/'):
        return 1
    return None


def _file_name(message, mime):
    """The customer's own file name, made safe; else one from the type."""
    # Photos, voice notes and videos arrive with no file name, and Django's
    # get_valid_filename raises on an empty or unusable one rather than
    # returning '': only a name worth keeping is tried.
    raw = os.path.basename(message.media_name or '').strip()
    if raw:
        try:
            return get_valid_filename(raw)[:120]
        except SuspiciousFileOperation:
            pass
    ext = mimetypes.guess_extension((mime or '').split(';')[0].strip()) or ''
    return f'{(message.message_type or "file").lower()}-{message.pk}{ext}'


# Paper sizes a file is matched to, in mm (either way round), within 6 mm.
PAPER = [('A3', 297, 420), ('A4', 210, 297), ('A5', 148, 210), ('A6', 105, 148),
         ('Letter', 215.9, 279.4), ('2 x 2 in', 50.8, 50.8)]


def paper_size(width_mm, height_mm, tolerance=6):
    """'A4', 'A3'..., or the size in mm when it matches none."""
    if not width_mm or not height_mm:
        return ''
    short, long_ = sorted((float(width_mm), float(height_mm)))
    for name, a, b in PAPER:
        if abs(short - a) <= tolerance and abs(long_ - b) <= tolerance:
            return name
    return f'{round(short)} x {round(long_)} mm'


def describe(content, name, mime):
    """
    What a file is, measured on arrival the way the counter measures it.
    Photos carry no trustworthy paper size, only pixels. Colour here is
    the file's, not the job's: a black-text CV saved by Word is a colour
    PDF, so Octos still asks colour or black and white. Never raises.
    """
    from decimal import Decimal

    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.jobs.services.file_metadata import measure
    from apps.storefront.services.inspection import _Carrier

    try:
        found = measure(_Carrier(SimpleUploadedFile(name or 'file', content, content_type=mime)))
    except Exception:
        logger.warning('Could not measure %s', name, exc_info=True)
        return {}
    keys = ('page_count', 'width_px', 'height_px', 'dpi', 'colour_mode')
    if not (mime or '').startswith('image/'):
        keys += ('width_mm', 'height_mm')
    info = {k: found.get(k) for k in keys if found.get(k) not in (None, '')}
    if 'width_mm' in info and 'height_mm' in info:
        info['paper'] = paper_size(info['width_mm'], info['height_mm'])
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in info.items()}
