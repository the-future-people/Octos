"""
Octos's approved WhatsApp messages (templates), at Meta (8 Nov 2026).

WhatsApp only lets a business message a customer more than 24 hours after
their last message with a template Meta has approved. The templates are the
ones the inbox's New message offers (START_TEMPLATES), so the two can't drift.

    python manage.py whatsapp_templates            # each one's status at Meta
    python manage.py whatsapp_templates --submit   # send the ones not there yet

Needs the WhatsApp token to carry whatsapp_business_management.

21 Nov 2026: the receipt and the statement too (services/templates.py),
whose header carries the receipt picture or the statement PDF. Meta wants a
sample of the header with the submission, uploaded through the app's
resumable upload; the app's id comes from the token (or WHATSAPP_APP_ID).
If Meta won't take the upload, the command says so, and the two can be made
by hand in WhatsApp Manager with the same name and wording.
"""
import re

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

EXAMPLES = {
    'order_ready': ['Ama', 'FP-WLB-05812'],
    'job_question': ['Ama', 'FP-WLB-05812'],
    'proforma_ready': ['Ama', 'PFI-WLB-2026-00030'],
    'general_followup': ['Ama'],
    'reconnect': ['Ama'],
    'owner_update': ['A discount on PFI-WLB-2026-00036 is waiting for your OK: GHS 1,967.48.'],
}

# The owner's private line (18 Nov 2026): the knock when his 24-hour window
# is shut. Not offered in the inbox. Its Open button opens the window, and
# Octos then sends what was waiting.
OWNER_TEMPLATES = {
    'owner_update': ('Octos update for you: {1}\n\nTap Open below to see the full details here.', ['Open']),
}


def _sample_image():
    """A receipt-shaped sample picture for Meta's review."""
    import io

    from PIL import Image, ImageDraw
    img = Image.new('RGB', (600, 800), 'white')
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 600, 110], fill=(200, 16, 46))
    draw.text((30, 40), 'FARHAT PRINTING PRESS  -  RECEIPT', fill='white')
    for n, line in enumerate(['Receipt RCP-WLB-2026-00123', 'A4 printing x 20', 'Amount paid  GHS 45.00',
                              'Thank you for choosing Farhat']):
        draw.text((30, 170 + n * 60), line, fill=(30, 30, 30))
    out = io.BytesIO()
    img.save(out, 'PNG')
    return out.getvalue(), 'image/png'


def _sample_pdf():
    """A sample statement PDF for Meta's review."""
    from decimal import Decimal
    from types import SimpleNamespace

    from django.utils import timezone

    from apps.finance.services.statement_pdf import build_statement_pdf
    now = timezone.now()
    job = SimpleNamespace(job_number='FP-WLB-2026-05812', title='A4 printing', estimated_cost=Decimal('300'),
                          amount_paid=Decimal('0'), balance_due=Decimal('300'), handed_over_at=now, created_at=now,
                          line_items=None)
    st = {'customer': SimpleNamespace(display_name='Ama Mensah', phone='0244000000'), 'owed': [job], 'current': [],
          'owed_total': Decimal('300'), 'current_total': Decimal('0'), 'total': Decimal('300')}
    return build_statement_pdf(st), 'application/pdf'


def _header_handle(content, mime, token, api_version):
    """Meta's handle for a sample file (resumable upload), needed to submit a template with a media header."""
    app_id = getattr(settings, 'WHATSAPP_APP_ID', '') or ''
    headers = {'Authorization': f'Bearer {token}'}
    if not app_id:
        app = requests.get(f'https://graph.facebook.com/{api_version}/app', headers=headers, timeout=30).json()
        app_id = app.get('id', '')
    if not app_id:
        raise CommandError("Couldn't find the app's id: set WHATSAPP_APP_ID.")
    session = requests.post(f'https://graph.facebook.com/{api_version}/{app_id}/uploads', headers=headers, timeout=30,
                            params={'file_length': len(content), 'file_type': mime}).json()
    if 'id' not in session:
        raise CommandError(f"Meta refused the upload: {session.get('error', {}).get('message', session)}")
    done = requests.post(f"https://graph.facebook.com/{api_version}/{session['id']}", timeout=60, data=content,
                         headers={'Authorization': f'OAuth {token}', 'file_offset': '0'}).json()
    if 'h' not in done:
        raise CommandError(f"Meta refused the upload: {done.get('error', {}).get('message', done)}")
    return done['h']


class Command(BaseCommand):
    help = "Octos's WhatsApp templates: their status at Meta, or --submit the missing ones."

    def add_arguments(self, parser):
        parser.add_argument('--submit', action='store_true', help='Submit the templates Meta does not have yet.')

    def handle(self, *args, submit=False, **options):
        from apps.communications.api.views import MARKETING_TEMPLATES, START_TEMPLATES
        from apps.communications.services.whatsapp_client import API_VERSION

        token = settings.WHATSAPP_ACCESS_TOKEN
        waba = settings.WHATSAPP_BUSINESS_ACCOUNT_ID
        if not token or not waba:
            raise CommandError('WHATSAPP_ACCESS_TOKEN and WHATSAPP_BUSINESS_ACCOUNT_ID must both be set.')
        base = f'https://graph.facebook.com/{API_VERSION}/{waba}/message_templates'
        headers = {'Authorization': f'Bearer {token}'}

        listed = requests.get(base, headers=headers, timeout=30,
                              params={'fields': 'name,status,language,category,rejected_reason', 'limit': 200})
        if listed.status_code != 200:
            raise CommandError(f"Meta refused the list: {listed.json().get('error', {}).get('message', listed.text)}")
        at_meta = {t['name']: t for t in listed.json().get('data', [])}

        from apps.communications.services.templates import MEDIA_TEMPLATES
        wanted = [(name, text, []) for name, text in START_TEMPLATES.items()]
        wanted += [(name, text, buttons) for name, (text, buttons) in OWNER_TEMPLATES.items()]
        wanted += [(name, spec['text'], []) for name, spec in MEDIA_TEMPLATES.items()]
        for name, text, buttons in wanted:
            found = at_meta.get(name)
            if found:
                why = f" ({found['rejected_reason']})" if found.get('rejected_reason') not in (None, '', 'NONE') else ''
                self.stdout.write(f"{name:16} {found['status']}{why}")
                continue
            if not submit:
                self.stdout.write(f'{name:16} not submitted yet')
                continue
            body = re.sub(r'\{(\d+)\}', r'{{\1}}', text)
            media = MEDIA_TEMPLATES.get(name)
            example = media['example'] if media else EXAMPLES.get(name, ['Ama', 'FP-WLB-05812'])
            payload = {
                'name': name, 'language': 'en',
                'category': 'MARKETING' if name in MARKETING_TEMPLATES else 'UTILITY',
                'components': [{'type': 'BODY', 'text': body, 'example': {'body_text': [example]}}],
            }
            if media:
                content, mime = _sample_image() if media['header'] == 'IMAGE' else _sample_pdf()
                try:
                    handle = _header_handle(content, mime, token, API_VERSION)
                except CommandError as refused:
                    self.stdout.write(f'{name:16} NOT SUBMITTED: {refused} Make it by hand in WhatsApp Manager.')
                    continue
                payload['components'].insert(0, {'type': 'HEADER', 'format': media['header'],
                                                 'example': {'header_handle': [handle]}})
            if buttons:
                payload['components'].append({'type': 'BUTTONS', 'buttons': [
                    {'type': 'QUICK_REPLY', 'text': b} for b in buttons]})
            sent = requests.post(base, headers=headers, json=payload, timeout=30)
            if sent.status_code in (200, 201):
                self.stdout.write(f"{name:16} submitted: {sent.json().get('status', 'PENDING')}")
            else:
                self.stdout.write(f"{name:16} REFUSED: {sent.json().get('error', {}).get('error_user_msg') or sent.json().get('error', {}).get('message', sent.text)}")
