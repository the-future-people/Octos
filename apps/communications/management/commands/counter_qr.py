"""
The counter QR link for a branch (Layer 2, Step 2.1).

    python manage.py counter_qr                     # every trading branch
    python manage.py counter_qr --branch Westland   # one branch
    python manage.py counter_qr --check             # did the last QR messages carry their signature?

Open the printed link on a phone, send the greeting as it is, then run --check.
"""
from django.core.management.base import BaseCommand

from apps.communications.assistant import qr

FARHAT_NUMBER = '233551969777'


class Command(BaseCommand):
    help = "Print each branch's counter QR link, or check recent arrivals for their signature."

    def add_arguments(self, parser):
        parser.add_argument('--branch', default='', help='A branch name (or part of it).')
        parser.add_argument('--number', default=FARHAT_NUMBER, help='The WhatsApp number, digits only.')
        parser.add_argument('--check', action='store_true', help='Show the latest counter presences.')

    def handle(self, *args, **options):
        if options['check']:
            return self._check()
        from apps.organization.models import Branch
        branches = Branch.objects.filter(is_active=True)
        if options['branch']:
            branches = branches.filter(name__icontains=options['branch'])
        else:
            branches = branches.filter(is_trading=True)
        for branch in branches:
            self.stdout.write(f'{branch.name} (id {branch.pk}):')
            self.stdout.write(f'  {qr.link(branch.pk, options["number"])}')
        if not branches:
            self.stdout.write('No matching branch.')

    def _check(self):
        from apps.spine import kinds
        from apps.spine.models import Event
        events = Event.objects.filter(kind=kinds.PRESENCE_COUNTER).order_by('-occurred_at')[:10]
        if not events:
            self.stdout.write('No counter presence recorded yet.')
        for e in events:
            how = 'SIGNED QR, verified' if e.payload.get('verified') else 'words only (no signature)'
            self.stdout.write(f'{e.occurred_at:%d %b %H:%M:%S}  chat {e.conversation_id}  {how}  '
                              f'branch {e.branch_id or "-"}')
