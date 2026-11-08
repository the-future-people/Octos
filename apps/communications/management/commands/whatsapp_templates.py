"""
Octos's approved WhatsApp messages (templates), at Meta (8 Nov 2026).

WhatsApp only lets a business message a customer more than 24 hours after
their last message with a template Meta has approved. The templates are the
ones the inbox's New message offers (START_TEMPLATES), so the two can't drift.

    python manage.py whatsapp_templates            # each one's status at Meta
    python manage.py whatsapp_templates --submit   # send the ones not there yet

Needs the WhatsApp token to carry whatsapp_business_management.
"""
import re

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

EXAMPLES = {
    'order_ready': ['Ama', 'FP-WLB-05812'],
    'job_question': ['Ama', 'FP-WLB-05812'],
    'proforma_ready': ['Ama', 'PFI-WLB-2026-00030'],
}


class Command(BaseCommand):
    help = "Octos's WhatsApp templates: their status at Meta, or --submit the missing ones."

    def add_arguments(self, parser):
        parser.add_argument('--submit', action='store_true', help='Submit the templates Meta does not have yet.')

    def handle(self, *args, submit=False, **options):
        from apps.communications.api.views import START_TEMPLATES
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

        for name, text in START_TEMPLATES.items():
            found = at_meta.get(name)
            if found:
                why = f" ({found['rejected_reason']})" if found.get('rejected_reason') not in (None, '', 'NONE') else ''
                self.stdout.write(f"{name:16} {found['status']}{why}")
                continue
            if not submit:
                self.stdout.write(f'{name:16} not submitted yet')
                continue
            body = re.sub(r'\{(\d+)\}', r'{{\1}}', text)
            payload = {
                'name': name, 'language': 'en', 'category': 'UTILITY',
                'components': [{'type': 'BODY', 'text': body,
                                'example': {'body_text': [EXAMPLES.get(name, ['Ama', 'FP-WLB-05812'])]}}],
            }
            sent = requests.post(base, headers=headers, json=payload, timeout=30)
            if sent.status_code in (200, 201):
                self.stdout.write(f"{name:16} submitted: {sent.json().get('status', 'PENDING')}")
            else:
                self.stdout.write(f"{name:16} REFUSED: {sent.json().get('error', {}).get('error_user_msg') or sent.json().get('error', {}).get('message', sent.text)}")
