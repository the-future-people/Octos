"""
A read-only look at who Octos knows, and how well.

    python manage.py contacts_report
    python manage.py contacts_report --show 40

Nothing is changed. It reads every customer, every storefront lead and
every app account, puts every phone number into full international form
the way the coming contacts work will (Ghana as the default, any other
country kept as its own), and reports:

- totals, and how many leads are linked to a customer;
- the numbers: valid Ghanaian, valid foreign, unreadable, missing;
- every number held by more than one record, sorted into the merge
  tiers: the same first name (would merge on evidence), different names
  (a shared line: flagged, never merged), and leads whose number
  matches a customer they are not linked to.

Run it again after any clean-up to see the change.
"""

import re
from collections import defaultdict

from django.core.management.base import BaseCommand

try:
    import phonenumbers
except ImportError:          # the report still runs; the fallback knows Ghana only
    phonenumbers = None


def international(raw, default_region='GH'):
    """(E.164, kind) where kind is 'GH', 'FOREIGN', 'INVALID' or 'EMPTY'."""
    raw = (raw or '').strip()
    if not raw:
        return None, 'EMPTY'
    if phonenumbers is not None:
        try:
            parsed = phonenumbers.parse(raw, default_region)
        except phonenumbers.NumberParseException:
            return None, 'INVALID'
        if not phonenumbers.is_valid_number(parsed):
            return None, 'INVALID'
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        return e164, ('GH' if parsed.country_code == 233 else 'FOREIGN')
    digits = re.sub(r'\D', '', raw)
    if raw.startswith('+') and not digits.startswith('233') and len(digits) >= 8:
        return '+' + digits, 'FOREIGN'
    if digits.startswith('233') and len(digits) == 12:
        return '+' + digits, 'GH'
    if digits.startswith('0') and len(digits) == 10:
        return '+233' + digits[1:], 'GH'
    return None, 'INVALID'


def first_word(name):
    return (name or '').strip().split(' ')[0].lower() if name else ''


class Command(BaseCommand):
    help = 'Read-only report on customers, leads and their numbers.'

    def add_arguments(self, parser):
        parser.add_argument('--show', type=int, default=25,
                            help='How many examples of each kind to list.')

    def handle(self, *args, show=25, **options):
        from apps.customers.models import CustomerProfile
        from apps.storefront.models import AppSession, Lead

        out = self.stdout.write
        if phonenumbers is None:
            out(self.style.WARNING('phonenumbers is not installed: numbers are read with a Ghana-only fallback.'))

        customers = list(CustomerProfile.objects.all())
        leads = list(Lead.objects.all())
        app_leads = set(AppSession.objects.filter(revoked_at__isnull=True).values_list('lead_id', flat=True))

        # ── Totals ───────────────────────────────────────────────────
        by_type = defaultdict(int)
        for c in customers:
            by_type[c.customer_type or '(none)'] += 1
        linked = sum(1 for l in leads if l.customer_id)
        out(self.style.MIGRATE_HEADING('\nTotals'))
        out(f'  Customers: {len(customers)}  ' + ', '.join(f'{k}: {v}' for k, v in sorted(by_type.items())))
        out(f'    walk-in records: {sum(1 for c in customers if c.is_walkin)}'
            f' | with a second number: {sum(1 for c in customers if c.secondary_phone)}'
            f' | with an email: {sum(1 for c in customers if c.email)}')
        out(f'  Storefront leads: {len(leads)} | linked to a customer: {linked} | not linked: {len(leads) - linked}')
        out(f'  App accounts signed in: {len(app_leads)}')

        # ── Every number, in international form ─────────────────────
        holders = defaultdict(list)          # e164 -> [(kind, record, name, which)]
        kinds = defaultdict(int)
        odd = defaultdict(list)              # 'INVALID' / 'FOREIGN' -> examples

        def take(raw, who, record, name, which):
            e164, kind = international(raw)
            kinds[kind] += 1
            if kind in ('INVALID', 'FOREIGN'):
                odd[kind].append(f'{who} #{record.pk} {name!r} {which}: {raw!r}' + (f' -> {e164}' if e164 else ''))
            if e164:
                holders[e164].append((who, record, name, which))

        for c in customers:
            name = getattr(c, 'full_name', '') or c.first_name
            take(c.phone, 'customer', c, name, 'phone')
            if c.secondary_phone:
                take(c.secondary_phone, 'customer', c, name, 'second')
        for l in leads:
            take(l.phone, 'lead', l, l.first_name, 'phone')

        out(self.style.MIGRATE_HEADING('\nNumbers'))
        out(f'  Ghanaian: {kinds["GH"]} | foreign: {kinds["FOREIGN"]} | unreadable: {kinds["INVALID"]} | missing: {kinds["EMPTY"]}')
        for kind, label in (('FOREIGN', 'Foreign numbers'), ('INVALID', 'Unreadable numbers')):
            if odd[kind]:
                out(f'  {label}:')
                for line in odd[kind][:show]:
                    out(f'    {line}')

        # ── Numbers held by more than one record ────────────────────
        same_name, shared, unlinked = [], [], []
        for e164, rows in holders.items():
            people = {(who, r.pk) for who, r, _, _ in rows}
            if len(people) < 2:
                continue
            customer_rows = [x for x in rows if x[0] == 'customer']
            lead_rows = [x for x in rows if x[0] == 'lead']
            cust_ids = {r.pk for _, r, _, _ in customer_rows}
            # A lead already linked to the customer holding this number is fine.
            lonely_leads = [x for x in lead_rows if x[1].customer_id not in cust_ids]
            if len(cust_ids) == 1 and lead_rows and not lonely_leads:
                continue
            names = {first_word(n) for _, _, n, _ in rows if first_word(n)}
            line = f'{e164}: ' + '; '.join(f'{who} #{r.pk} {n!r} ({which})' for who, r, n, which in rows)
            if len(cust_ids) == 1 and lonely_leads and len(names) <= 1:
                unlinked.append(line)
            elif len(names) <= 1:
                same_name.append(line)
            else:
                shared.append(line)

        out(self.style.MIGRATE_HEADING('\nNumbers on more than one record'))
        out(f'  Same first name (would merge on evidence): {len(same_name)}')
        out(f'  Different names (a shared line: flagged, never merged): {len(shared)}')
        out(f'  A lead matching a customer it is not linked to: {len(unlinked)}')
        for label, rows in (('Same first name', same_name), ('Different names', shared), ('Unlinked lead', unlinked)):
            if rows:
                out(f'\n  {label}:')
                for line in rows[:show]:
                    out(f'    {line}')
        out('')