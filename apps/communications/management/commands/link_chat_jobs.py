"""
python manage.py link_chat_jobs [--days 14] [--apply]

Links the jobs recorded from a chat before 17 Nov 2026 to that chat. Until
then the link was never made (the screen never got the new job's id), so
those jobs' receipts couldn't reach a customer writing from a WhatsApp
username: "This receipt has no phone number to send it to."

A job is matched to a chat when:
  - its note says who it was for: "For Ama (WhatsApp @ama_prints)", the note
    a job gets when recorded from a username chat with no customer record; or
  - its customer is the chat's customer, and they wrote in that chat in the
    two hours before the job was made: recorded while talking to them.

Without --apply it only lists what it would link. Jobs already linked to a
chat are left alone.
"""
import re
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

USERNAME_NOTE = re.compile(r'\(WhatsApp @([\w.]+)\)')
WROTE_WITHIN = timedelta(hours=2)


def match_chat(job):
    """The chat this job was recorded from, or None."""
    from apps.communications.models import Conversation, Message

    chats = Conversation.objects.filter(channel=Conversation.WHATSAPP).exclude(status=Conversation.SPAM)
    named = USERNAME_NOTE.search(job.notes or '')
    if named:
        chat = chats.filter(contact_username__iexact=named.group(1)).order_by('-pk').first()
        if chat is not None:
            return chat
    if job.customer_id:
        wrote = Message.objects.filter(
            direction=Message.INBOUND,
            created_at__gte=job.created_at - WROTE_WITHIN, created_at__lte=job.created_at,
        )
        return (chats.filter(customer_id=job.customer_id, messages__in=wrote)
                .distinct().order_by('-last_message_at').first())
    return None


class Command(BaseCommand):
    help = 'Link jobs recorded from a WhatsApp chat (before 17 Nov 2026) to that chat.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=14, help='How far back to look (default 14).')
        parser.add_argument('--apply', action='store_true', help='Make the links; without it, only list them.')

    def handle(self, *args, **opts):
        from apps.jobs.models import Job

        since = timezone.now() - timedelta(days=opts['days'])
        jobs = (Job.objects.filter(created_at__gte=since, conversations__isnull=True)
                .exclude(status__in=['DRAFT', 'CANCELLED', 'VOIDED']).order_by('created_at'))
        found = 0
        for job in jobs:
            chat = match_chat(job)
            if chat is None:
                continue
            found += 1
            who = chat.contact_name or (f'@{chat.contact_username}' if chat.contact_username else chat.contact_phone)
            self.stdout.write(f'{job.job_number}  →  chat {chat.pk} ({who})')
            if opts['apply']:
                chat.jobs.add(job)
        verb = 'Linked' if opts['apply'] else 'Would link'
        self.stdout.write(self.style.SUCCESS(f'{verb} {found} job(s).'))
        if found and not opts['apply']:
            self.stdout.write('Run again with --apply to link them.')
