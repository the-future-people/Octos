"""
Octos opens the files in a chat (20 Nov 2026).

Khofi asked "has Amoree been sorted yet?" and Octos could only say a PDF
had gone to her: it knew the file's name, not what was in it. "You can't
read the file?" Now it can:

  PDF            the text of its first pages (pypdf)
  Word (.docx)   the text of the document
  text, csv      as written
  photos         the picture itself, for Octos to look at (made smaller first)

A scanned PDF with no text in it, or a format we can't open (PowerPoint,
CorelDRAW, Photoshop), is said plainly, never guessed at.
"""
import base64
import io
import logging
import re
import zipfile

logger = logging.getLogger(__name__)

TEXT_LIMIT = 6000        # characters handed to Octos from one file
PDF_PAGES = 8            # pages read from a PDF
IMAGE_SIDE = 1400        # longest side of a picture shown to Octos
MAX_BYTES = 25 * 1024 * 1024


def _bytes(message):
    """The file's bytes, from our storage, or fetched from WhatsApp if we never kept it."""
    if message.media_file:
        with message.media_file.open('rb') as handle:
            return handle.read(MAX_BYTES + 1)
    if message.media_id:
        from apps.communications.services import whatsapp_media
        content, _mime = whatsapp_media.download(message.media_id)
        return content
    return b''


def _kind(message):
    mime = (message.media_mime or '').lower()
    name = (message.media_name or (message.media_file.name if message.media_file else '') or '').lower()
    if mime == 'application/pdf' or name.endswith('.pdf'):
        return 'pdf'
    if 'wordprocessingml' in mime or name.endswith('.docx'):
        return 'docx'
    if mime.startswith('text/') or name.endswith(('.txt', '.csv')):
        return 'text'
    if mime.startswith('image/') or message.message_type == 'IMAGE':
        return 'image'
    return 'other'


def _pdf_text(content):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for number, page in enumerate(reader.pages[:PDF_PAGES], start=1):
        words = (page.extract_text() or '').strip()
        if words:
            pages.append(f'[page {number}]\n{words}')
    return '\n\n'.join(pages), len(reader.pages)


def _docx_text(content):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        xml = z.read('word/document.xml').decode('utf-8', 'ignore')
    xml = re.sub(r'</w:p>', '\n', xml)
    xml = re.sub(r'<w:tab/>', '\t', xml)
    text = re.sub(r'<[^>]+>', '', xml)
    import html
    return html.unescape(re.sub(r'\n{3,}', '\n\n', text)).strip()


def _small_jpeg(content):
    from PIL import Image
    img = Image.open(io.BytesIO(content))
    img = img.convert('RGB')
    img.thumbnail((IMAGE_SIDE, IMAGE_SIDE))
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=80)
    return out.getvalue()


def read(message):
    """
    {'file', 'what', 'text'} for a document, {'file', 'what', '_image': (mime, base64)}
    for a picture (the caller shows it to the model), or {'file', 'error'}.
    """
    name = message.media_name or 'the file'
    if message.message_type not in ('IMAGE', 'DOCUMENT') and not message.media_file:
        return {'file': name, 'error': 'That message has no file to open.'}
    kind = _kind(message)
    if kind == 'other':
        return {'file': name, 'error': "I can't open this kind of file yet (only PDFs, Word files, text and "
                                       'photos). Someone at the shop would need to look at it.'}
    try:
        content = _bytes(message)
    except Exception:
        logger.warning('Could not fetch file %s for reading', message.pk, exc_info=True)
        return {'file': name, 'error': "I couldn't get the file: it may have expired on WhatsApp."}
    if not content:
        return {'file': name, 'error': "I couldn't get the file."}
    if len(content) > MAX_BYTES:
        return {'file': name, 'error': 'The file is too big for me to open here.'}
    try:
        if kind == 'image':
            return {'file': name, 'what': 'a picture: look at it',
                    '_image': ('image/jpeg', base64.b64encode(_small_jpeg(content)).decode())}
        if kind == 'pdf':
            text, pages = _pdf_text(content)
            what = f'PDF, {pages} page{"s" if pages != 1 else ""}'
            if not text:
                return {'file': name, 'what': what,
                        'error': 'This PDF has no text in it (it is probably a scan), so I can only see that '
                                 'it is there.'}
            if pages > PDF_PAGES:
                what += f' (I read the first {PDF_PAGES})'
        elif kind == 'docx':
            text, what = _docx_text(content), 'Word document'
        else:
            text, what = content.decode('utf-8', 'ignore'), 'text'
    except Exception:
        logger.warning('Could not read file %s', message.pk, exc_info=True)
        return {'file': name, 'error': "I couldn't open this file: it may be damaged or locked."}
    cut = len(text) > TEXT_LIMIT
    return {'file': name, 'what': what, 'text': text[:TEXT_LIMIT] + ('\n[…the rest is cut off]' if cut else '')}
