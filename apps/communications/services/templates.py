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

# The text-only ones: the inbox's New message offers them, and Octos uses them
# on the owner's word for a customer who never wrote or whose window shut.
START_TEMPLATES = {
    'order_ready': 'Hello {1}, your order {2} is ready to collect at Farhat Printing Press, Westland.',
    'job_question': 'Hello {1}, about your job {2}: please reply when you can.',
    'proforma_ready': 'Hello {1}, your proforma {2} is ready. Reply to receive it here.',
    # Checking in after a past job (utility), and reaching customers who have
    # gone quiet (marketing), in Farhat's own warm voice (Khofi, 8 Nov 2026).
    'general_followup': ('Hello {1}, it\u2019s Farhat Printing Press at Westland. We were thinking about the '
                         'last job we did for you and wanted to check in. How did it all turn out? We\u2019d love '
                         'to hear from you whenever you have a moment.'),
    'reconnect': ('Hello {1}! It\u2019s the team at Farhat Printing Press, Westland. We haven\u2019t seen you in a '
                  'while and just wanted to say we\u2019re still here for you, from a single copy to a big order. '
                  'Send us a message anytime. If you\u2019d prefer not to hear from us, just let us know.'),
    # Thanking a customer for a particular order (22 Nov 2026: Khofi wanted to
    # thank Mr Hemeng for a GHS 1,967.48 order, and he had never written to us).
    'thank_you_order': ('Hello {1}, thank you for your order {2} with Farhat Printing Press. We truly appreciate '
                        'your business, and it was a pleasure working on it for you \U0001F64F'),
}
# Marketing, by WhatsApp's rules: never sent to a customer who asked not to be.
MARKETING_TEMPLATES = {'reconnect'}

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


def text_of(name):
    """The approved wording of any of our templates, or None."""
    if name in MEDIA_TEMPLATES:
        return MEDIA_TEMPLATES[name]['text']
    return START_TEMPLATES.get(name)


def fill(text, params):
    """The body as the customer reads it: {1}, {2}… replaced in order."""
    return re.sub(r'\{(\d+)\}', lambda m: str(params[int(m.group(1)) - 1]), text)


def hello_name(name):
    """A template blank can't be empty: no name we trust reads 'Hello there'."""
    return (name or '').strip() or 'there'
