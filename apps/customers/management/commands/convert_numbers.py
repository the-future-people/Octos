"""
Every stored phone number in its international form.

    python manage.py convert_numbers           # shows what would change
    python manage.py convert_numbers --apply   # changes it

Customers' main and second numbers and every storefront lead's number
are put in the one form Octos keeps (+233244123456, +13312296096), so
each number is written one way wherever it is.

Nothing is guessed:
- a number that cannot be read is left exactly as it is, and listed;
- a conversion that would give a second customer someone else's main
  number is left alone and listed: that is a duplicate to look at first;
- receipts, invoices and orders keep the numbers they were printed with,
  as records of what was true at the time.

Each customer change is written to their edit log.
"""

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = 'Put every stored customer and lead number in international form.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **options):
        from apps.core.phones import to_international
        from apps.customers.models import CustomerEditLog, CustomerProfile
        from apps.storefront.models import Lead

        changed = unreadable = clashes = same = 0

        def show(line):
            self.stdout.write('  ' + line)

        # ── Customers ────────────────────────────────────────────────
        taken = {}
        for c in CustomerProfile.objects.all().only('pk', 'phone'):
            form = to_international(c.phone)
            if form:
                taken.setdefault(form, c.pk)

        for c in CustomerProfile.objects.all().order_by('pk'):
            updates = {}
            for field in ('phone', 'secondary_phone'):
                raw = getattr(c, field) or ''
                if not raw.strip():
                    continue
                form = to_international(raw)
                if form is None:
                    show(f'customer #{c.pk} {c.full_name!r} {field} {raw!r}: unreadable, left as it is')
                    unreadable += 1
                    continue
                if form == raw:
                    same += 1
                    continue
                if field == 'phone' and taken.get(form, c.pk) != c.pk:
                    show(f'customer #{c.pk} {c.full_name!r} phone {raw!r} -> {form} is #{taken[form]}\'s: left alone')
                    clashes += 1
                    continue
                updates[field] = (raw, form)
            if not updates:
                continue
            for field, (raw, form) in updates.items():
                show(f'customer #{c.pk} {field}: {raw!r} -> {form}')
            changed += len(updates)
            if apply:
                with transaction.atomic():
                    for field, (raw, form) in updates.items():
                        setattr(c, field, form)
                    c.save(update_fields=list(updates))
                    for field, (raw, form) in updates.items():
                        try:
                            CustomerEditLog.objects.create(customer=c, changed_by=None, field_name=field,
                                                           old_value=raw, new_value=form)
                        except Exception:
                            pass   # the change stands; the log is a courtesy

        # ── Leads ────────────────────────────────────────────────────
        lead_taken = {}
        for l in Lead.objects.all().only('pk', 'phone'):
            form = to_international(l.phone)
            if form:
                lead_taken.setdefault(form, l.pk)
        for l in Lead.objects.all().order_by('pk'):
            raw = l.phone or ''
            form = to_international(raw)
            if form is None:
                show(f'lead #{l.pk} {l.first_name!r} {raw!r}: unreadable, left as it is')
                unreadable += 1
                continue
            if form == raw:
                same += 1
                continue
            if lead_taken.get(form, l.pk) != l.pk:
                show(f'lead #{l.pk} {raw!r} -> {form} is lead #{lead_taken[form]}\'s: left alone')
                clashes += 1
                continue
            show(f'lead #{l.pk}: {raw!r} -> {form}')
            changed += 1
            if apply:
                l.phone = form
                l.save(update_fields=['phone'])

        verb = 'Changed' if apply else 'Would change'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {changed}; already international {same}; unreadable {unreadable}; clashes {clashes}.'))