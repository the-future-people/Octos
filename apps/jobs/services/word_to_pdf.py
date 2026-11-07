"""
Customers' Word files, turned into PDFs (7 Nov 2026).

Customers send what they have, and what they have is often a .docx. Each
one becomes a PDF the moment it arrives, and from then on the PDF is what
is measured, judged, quoted and printed: the floor prints exactly what was
checked and priced. LibreOffice does the converting, with no screen; fonts
metric-compatible with Word's keep the pages breaking where Word breaks
them (installed in the Dockerfile).

Each conversion runs in a folder and profile of its own, so two at once
cannot trip over each other, and gives up after TIMEOUT seconds.
"""
import os
import shutil
import subprocess
import tempfile

WORD_TYPES = {
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.oasis.opendocument.text',
    'application/rtf',
    'text/rtf',
}
WORD_EXTENSIONS = ('.docx', '.doc', '.odt', '.rtf')
TIMEOUT = 90


class ConversionFailed(Exception):
    """The file could not be turned into a PDF; the message says why, plainly."""


def is_word(name, content_type=''):
    """A Word-like document, by its type or, failing that, its name."""
    kind = (content_type or '').split(';')[0].strip().lower()
    if kind in WORD_TYPES:
        return True
    if kind == 'application/pdf' or kind.startswith('image/'):
        return False
    return (name or '').lower().endswith(WORD_EXTENSIONS)


def pdf_name(name):
    """project.docx -> project.pdf"""
    stem = os.path.splitext(os.path.basename(name or ''))[0] or 'document'
    return f'{stem}.pdf'


def to_pdf(content, name):
    """The PDF bytes of a Word-like document. Raises ConversionFailed."""
    soffice = shutil.which('soffice') or shutil.which('libreoffice')
    if not soffice:
        raise ConversionFailed("Word files can't be converted on this server yet.")
    lowered = (name or '').lower()
    ext = next((e for e in WORD_EXTENSIONS if lowered.endswith(e)), '.docx')
    with tempfile.TemporaryDirectory(prefix='octos-word-') as work:
        source = os.path.join(work, 'input' + ext)
        with open(source, 'wb') as handle:
            handle.write(content)
        profile = os.path.join(work, 'profile')
        command = [soffice, f'-env:UserInstallation=file://{profile}', '--headless', '--norestore',
                   '--nologo', '--nodefault', '--convert-to', 'pdf', '--outdir', work, source]
        try:
            done = subprocess.run(command, capture_output=True, timeout=TIMEOUT,
                                  env={**os.environ, 'HOME': work})
        except subprocess.TimeoutExpired:
            raise ConversionFailed('That Word file took too long to convert.')
        out = os.path.join(work, 'input.pdf')
        if done.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
            raise ConversionFailed("That Word file couldn't be converted.")
        with open(out, 'rb') as handle:
            return handle.read()
