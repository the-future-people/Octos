"""
Carry today's single "works with" links into proper links.

    python manage.py carry_affiliations           # shows what it would do
    python manage.py carry_affiliations --apply   # does it

Every individual whose record points at a business or institution gets a
link to it, as a member, ended if the old link was switched off. The old
field stays as it is, so nothing that reads it changes yet. Safe to run
again: a link already there is left alone.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Carry the single affiliation field into memberships.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **options):
        from apps.customers.models import CustomerProfile, Membership

        made = kept = 0
        for person in CustomerProfile.objects.filter(affiliation__isnull=False).select_related('affiliation'):
            org = person.affiliation
            if Membership.objects.filter(person=person, organisation=org).exists():
                kept += 1
                continue
            state = 'active' if person.affiliation_active else 'ended'
            self.stdout.write(f'  #{person.pk} {person.full_name!r} -> {org.company_name or org.full_name!r} ({state})')
            if apply:
                Membership.objects.create(
                    person=person, organisation=org, role=Membership.Role.MEMBER,
                    ended_at=None if person.affiliation_active else timezone.now(),
                    note='Carried from the earlier "works with" field',
                )
            made += 1
        verb = 'Made' if apply else 'Would make'
        self.stdout.write(self.style.SUCCESS(f'{verb} {made} link(s); {kept} already there.'))