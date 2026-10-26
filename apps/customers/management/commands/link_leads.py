"""
Link each storefront lead to the customer it already is.

    python manage.py link_leads           # shows what it would link
    python manage.py link_leads --apply   # links them

A lead is the app or website's record of someone; a customer is the
counter's. Where a lead's number matches exactly one customer's (either
of their numbers, however it was stored) and the names agree (titles
aside, any order, a first name with a full name), they are the same
person, and the lead is linked. Nothing else changes: no money moves,
no record is merged or removed. Anything less certain is listed, not
linked.
"""

from django.core.management.base import BaseCommand
from django.db.models import Q


class Command(BaseCommand):
    help = 'Link storefront leads to the customers they already are.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **options):
        from apps.core.phones import lookup_forms, to_international
        from apps.customers.identity import names_agree
        from apps.customers.models import CustomerProfile
        from apps.storefront.models import Lead

        linked = unsure = none = 0
        for lead in Lead.objects.filter(customer__isnull=True).order_by('pk'):
            if not to_international(lead.phone):
                self.stdout.write(f'  lead #{lead.pk} {lead.first_name!r}: number {lead.phone!r} is not real, left alone')
                unsure += 1
                continue
            forms = lookup_forms(lead.phone)
            matches = list(CustomerProfile.objects.filter(Q(phone__in=forms) | Q(secondary_phone__in=forms)))
            if not matches:
                none += 1
                continue
            agreeing = [c for c in matches if names_agree(lead.first_name, getattr(c, 'full_name', '') or c.first_name)]
            if len(agreeing) == 1:
                c = agreeing[0]
                self.stdout.write(f'  lead #{lead.pk} {lead.first_name!r} -> customer #{c.pk} {c.full_name!r}')
                if apply:
                    lead.customer = c
                    lead.save(update_fields=['customer'])
                linked += 1
            else:
                names = ', '.join(f'#{c.pk} {c.full_name!r}' for c in matches)
                self.stdout.write(f'  lead #{lead.pk} {lead.first_name!r}: not certain ({names}), left alone')
                unsure += 1

        verb = 'Linked' if apply else 'Would link'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {linked}; {unsure} left alone as not certain; {none} with no customer yet.'))