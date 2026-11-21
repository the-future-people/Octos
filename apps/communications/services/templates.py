"""
Approved WhatsApp messages that carry a picture or a document (21 Nov 2026).

WhatsApp lets a business write to someone more than 24 hours after their
last message only with a template Meta has approved (that's how Uber and
Bolt reach you). The inbox's text-only ones live in START_TEMPLATES; these
carry the receipt picture or the statement PDF in their header, so a
receipt or statement reaches a customer whose window is shut, or who never
wrote to us at all.

Each must be approved in WhatsApp Manager under this exact name, in English
(python manage.py whatsapp_templates --submit sends them, with a sample).
"""
import re

MEDIA_TEMPLATES = {
    'receipt_ready': {
        'header': 'IMAGE',
        'text': ('Hello {1}, here is your receipt from Farhat Printing Press for {2}. '
                 'Thank you for choosing Farhat 🙏'),
        'example': ['Ama', 'GHS 45.00'],
    },
    'account_statement': {
        'header': 'DOCUMENT',
        'text': ('Hello {1}, here is your statement from Farhat Printing Press. Total due: {2}. '
                 'Each job is listed by its number, so please tell us which one you are paying for. Thank you.'),
        'example': ['Ama', 'GHS 340.00'],
    },
}


def fill(text, params):
    """The body as the customer reads it: {1}, {2}… replaced in order."""
    return re.sub(r'\{(\d+)\}', lambda m: str(params[int(m.group(1)) - 1]), text)


def hello_name(name):
    """A template blank can't be empty: no name we trust reads 'Hello there'."""
    return (name or '').strip() or 'there'
