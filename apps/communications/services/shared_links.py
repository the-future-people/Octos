"""
Links to files that customers send instead of the file (27 Nov 2026).

Ekd sent two Adobe Acrobat links; Octos asked for the PDFs and Kingsford
opened the links himself. Khofi: Octos should open them and read them.

A link we can open becomes the customer's file in the chat: a document
message from them, "fetching" until it is saved, then measured like any
file they send (pages, paper, colour), so Octos prices it and the team
opens it like any other. Octos answers the message with the link, which
waits while the file is fetched (brain._still_reading, 3 minutes at most). If it can't be opened (private, or gone) the
message says so and Octos asks for the file itself.

    Google Drive and Docs   a public file, or a Doc/Sheet/Slides as PDF
    Dropbox                 any shared file (dl=1)
    OneDrive                a shared file, through its public shares API
    WeTransfer              a transfer of one file

Not opened: Adobe Acrobat and Canva links need their owner's sign-in. The
team opens those; Octos asks only what's missing and promises no price.

Turning a link into a download is pure (direct_url) and tested; fetching
runs on the worker (tasks.fetch_shared_link), never in the webhook.
"""
import base64
import logging
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

from apps.communications.models import Message

logger = logging.getLogger(__name__)

URL = re.compile(r'https?://[^\s<>"]+[^\s<>".,;:!?)\]\']')
MAX_LINKS = 5            # one message never fetches more than this
TIMEOUT = 30
HEADERS = {'User-Agent': 'Mozilla/5.0 (Octos; Farhat Printing Press) files-from-links'}
KIND = Message.FROM_LINK

# Where a link points, by host: (provider, can we open it ourselves).
PROVIDERS = [
    (re.compile(r'(^|\.)(drive|docs)\.google\.com$'), 'Google Drive', True),
    (re.compile(r'(^|\.)dropbox\.com$'), 'Dropbox', True),
    (re.compile(r'(^|\.)(onedrive\.live\.com|1drv\.ms)$'), 'OneDrive', True),
    (re.compile(r'(^|\.)(wetransfer\.com|we\.tl)$'), 'WeTransfer', True),
    (re.compile(r'(^|\.)acrobat\.adobe\.com$'), 'Adobe Acrobat', False),
    (re.compile(r'(^|\.)canva\.com$'), 'Canva', False),
]
# What a file from a link may be: printable things, never a web page.
FILE_TYPES = ('application/pdf', 'image/', 'application/msword', 'application/vnd.openxmlformats',
              'application/vnd.ms-', 'application/octet-stream', 'application/zip')


class LinkError(Exception):
    """A link that won't give us its file: why, in a word ('private', 'gone', 'too_big', 'not_a_file')."""


def provider(url):
    """('Google Drive', True) for a link we know, else None."""
    host = (urlparse(url).hostname or '').lower()
    for pattern, name, opens in PROVIDERS:
        if pattern.search(host):
            return name, opens
    return None


def links_in(text):
    """Every shared-document link in a message, in order, once each."""
    seen, found = set(), []
    for url in URL.findall(text or ''):
        if url not in seen and provider(url):
            seen.add(url)
            found.append(url)
    return found


def direct_url(url):
    """
    The address that hands over the file itself, or None when only a
    person can open it (Adobe, Canva) or the link isn't one we know.
    WeTransfer needs a call first (see _wetransfer), so it comes back as is.
    """
    known = provider(url)
    if not known or not known[1]:
        return None
    name = known[0]
    parts = urlparse(url)
    if name == 'Google Drive':
        doc = re.search(r'/(document|spreadsheets|presentation)/d/([\w-]+)', parts.path)
        if doc:
            kind, file_id = doc.groups()
            export = 'export/pdf' if kind == 'presentation' else 'export?format=pdf'
            return f'https://docs.google.com/{kind}/d/{file_id}/{export}'
        found = re.search(r'/file/d/([\w-]+)', parts.path)
        file_id = found.group(1) if found else (parse_qs(parts.query).get('id') or [None])[0]
        if not file_id:
            return None
        return f'https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t'
    if name == 'Dropbox':
        query = parse_qs(parts.query)
        query.pop('dl', None)
        query['dl'] = ['1']
        return urlunparse(parts._replace(query=urlencode(query, doseq=True)))
    if name == 'OneDrive':
        token = base64.urlsafe_b64encode(url.encode()).decode().rstrip('=')
        return f'https://api.onedrive.com/v1.0/shares/u!{token}/root/content'
    return url  # WeTransfer: resolved when fetched


def _wetransfer(url, session):
    """A WeTransfer link's download address: the short link opened, then its download asked for."""
    if 'we.tl' in (urlparse(url).hostname or ''):
        url = session.get(url, timeout=TIMEOUT, allow_redirects=True).url
    found = re.search(r'/downloads/(\w+)/(?:\w+/)?(\w+)', urlparse(url).path)
    if not found:
        raise LinkError('not_a_file')
    transfer, security = found.groups()
    answer = session.post(f'https://wetransfer.com/api/v4/transfers/{transfer}/download',
                          json={'security_hash': security, 'intent': 'entire_transfer'}, timeout=TIMEOUT)
    if answer.status_code in (403, 404):
        raise LinkError('gone')
    answer.raise_for_status()
    direct = (answer.json() or {}).get('direct_link')
    if not direct:
        raise LinkError('gone')
    return direct


def download(url):
    """
    (bytes, mime type, file name) for a shared link. LinkError when it
    can't be had; requests errors (a dropped connection) are tried again
    by the task.
    """
    from apps.communications.services.whatsapp_media import MAX_BYTES
    session = requests.Session()
    session.headers.update(HEADERS)
    target = direct_url(url)
    if target is None:
        raise LinkError('needs_sign_in')
    if provider(url)[0] == 'WeTransfer':
        target = _wetransfer(url, session)
    with session.get(target, timeout=TIMEOUT, stream=True, allow_redirects=True) as response:
        if response.status_code in (401, 403):
            raise LinkError('private')
        if response.status_code in (404, 410):
            raise LinkError('gone')
        response.raise_for_status()
        mime = (response.headers.get('Content-Type') or '').split(';')[0].strip().lower()
        if mime.startswith('text/html') or not mime.startswith(FILE_TYPES):
            # A sign-in or "request access" page instead of the file.
            raise LinkError('private' if mime.startswith('text/html') else 'not_a_file')
        size = int(response.headers.get('Content-Length') or 0)
        if size > MAX_BYTES:
            raise LinkError('too_big')
        chunks, total = [], 0
        for chunk in response.iter_content(64 * 1024):
            total += len(chunk)
            if total > MAX_BYTES:
                raise LinkError('too_big')
            chunks.append(chunk)
        return b''.join(chunks), mime, _name(response, url)


def _name(response, url):
    """The file's own name from the download, else one from the link."""
    disposition = response.headers.get('Content-Disposition') or ''
    found = re.search(r"filename\*=UTF-8''([^;]+)", disposition) or re.search(r'filename="?([^";]+)"?', disposition)
    if found:
        from urllib.parse import unquote
        return unquote(found.group(1)).strip()[:255]
    tail = urlparse(url).path.rstrip('/').rsplit('/', 1)[-1]
    return tail if '.' in tail else ''


def open_links(conversation, message):
    """
    For each link in a customer's message that we can open: a document
    message from them, fetching, and the worker sent to fetch it. Returns
    the new messages. Links only a person can open are left in the text.
    """
    from django.db import transaction
    from apps.communications.tasks import fetch_shared_link
    made = []
    for url in links_in(message.body)[:MAX_LINKS]:
        name, opens = provider(url)
        if not opens:
            continue
        held = Message.objects.create(
            conversation=conversation, direction=Message.INBOUND, channel=message.channel,
            message_type=Message.DOCUMENT, kind=KIND, body='', reply_to=message,
            media_name=f'File from {name}', media_info={'fetching': True, 'link': url, 'from': name},
        )
        transaction.on_commit(lambda pk=held.pk: fetch_shared_link.delay(pk))
        made.append(held)
    return made


def fetch(message_id):
    """The worker's half: download the link's file onto its message, then wake Octos for it."""
    from apps.communications.services import whatsapp_media
    message = Message.objects.select_related('conversation').get(pk=message_id)
    if message.media_file or message.file_deleted_at:
        return message
    url = (message.media_info or {}).get('link')
    try:
        content, mime, name = download(url)
    except LinkError as why:
        failed(message, str(why))
        return message
    if name:
        Message.objects.filter(pk=message.pk).update(media_name=name[:255])
        message.media_name = name[:255]
    # No wake: the customer's message with the link is the one Octos answers,
    # and it has been waiting for this file (brain._still_reading).
    return whatsapp_media.keep(message, content, mime)


def failed(message, why):
    """The chat says the link couldn't be opened, and Octos answers knowing why."""
    info = {'failed': why, 'link': (message.media_info or {}).get('link'),
            'from': (message.media_info or {}).get('from')}
    Message.objects.filter(pk=message.pk).update(media_info=info)
    message.media_info = info
    from apps.communications.services.whatsapp_media import _announce
    _announce(message)
    logger.info('Shared link for message %s not opened: %s', message.pk, why)
