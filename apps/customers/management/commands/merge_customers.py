"""
Merge customers who are plainly the same person.

    python manage.py merge_customers           # shows what it would merge
    python manage.py merge_customers --apply   # merges

A pair is merged when the same number is on two customer records and the
names agree (titles aside, any order). The older record survives with
its name and title; everything pointing at the newer one moves to it,
found from the model itself so nothing is missed; its number becomes the
survivor's second (a third goes in the notes until a person can hold
many numbers); blank fields are filled from it; visits and spend are
added together.

A wallet balance on the newer record stops the merge: money moves only
on proof that one person controls both numbers, never on a name. Every
merge keeps a snapshot of the record that went, so it can be undone.
"""

from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.forms.models import model_to_dict

FILLABLE = ['email', 'address', 'company_name', 'date_of_birth', 'gender', 'title', 'title_other',
            'last_name', 'preferred_branch', 'branch', 'institution_subtype', 'affiliation']


def _numbers(c):
    from apps.core.phones import to_international
    return {n for n in (to_international(c.phone), to_international(c.secondary_phone)) if n}


def find_pairs():
    """(survivor, duplicate, number) for same-number, same-name customers."""
    from apps.customers.identity import names_agree
    from apps.customers.models import CustomerProfile

    by_number = defaultdict(list)
    for c in CustomerProfile.objects.all().order_by('created_at', 'pk'):
        for n in _numbers(c):
            by_number[n].append(c)
    pairs, seen, companies = [], set(), []
    for number, people in by_number.items():
        if len(people) < 2:
            continue
        keep = people[0]
        for other in people[1:]:
            key = (keep.pk, other.pk)
            if key in seen or not names_agree(keep.full_name, other.full_name):
                continue
            seen.add(key)
            # Only records of the same kind. A business account shows its
            # representative's name, so a person and their company agree
            # by name and are still two customers: flagged, never merged.
            if (keep.customer_type or 'INDIVIDUAL') != (other.customer_type or 'INDIVIDUAL'):
                companies.append((keep, other, number))
                continue
            pairs.append((keep, other, number))
    find_pairs.companies = companies
    return pairs


@transaction.atomic
def merge(keep, dup, reason):
    from apps.customers.models import CustomerMerge, CustomerProfile
    keep = CustomerProfile.objects.select_for_update().get(pk=keep.pk)
    dup = CustomerProfile.objects.select_for_update().get(pk=dup.pk)
    if (dup.wallet_balance or 0) != 0:
        raise ValueError(f'#{dup.pk} has a wallet balance: money moves only on proof')

    snapshot = {k: (str(v) if v is not None else None) for k, v in model_to_dict(dup).items()}
    snapshot['created_at'] = dup.created_at.isoformat() if getattr(dup, 'created_at', None) else None

    # Everything that points at the duplicate, from the model itself.
    moved = {}
    for rel in CustomerProfile._meta.related_objects:
        if rel.related_model._meta.label == 'customers.CustomerMerge':
            continue
        field = rel.field.name
        label = f'{rel.related_model._meta.label}.{field}'
        if rel.one_to_many:
            qs = rel.related_model._default_manager.filter(**{field: dup})
            pks = list(qs.values_list('pk', flat=True))
            if pks:
                qs.update(**{field: keep})
                moved[label] = pks
        elif rel.one_to_one:
            other = rel.related_model._default_manager.filter(**{field: dup}).first()
            if other is not None:
                taken = rel.related_model._default_manager.filter(**{field: keep}).exists()
                setattr(other, field, None if taken else keep)
                other.save(update_fields=[field])
                moved[label] = [other.pk] if not taken else []
        elif rel.many_to_many:
            through = getattr(dup, rel.get_accessor_name())
            items = list(through.all())
            if items:
                getattr(keep, rel.get_accessor_name()).add(*items)
                moved[label] = [i.pk for i in items]

    # Numbers: the duplicate's become the survivor's.
    from apps.core.phones import to_international
    fields, filled, notes = [], {}, []
    known = _numbers(keep)
    for number in (dup.phone, dup.secondary_phone):
        form = to_international(number)
        if not number or (form and form in known):
            continue
        if not keep.secondary_phone:
            keep.secondary_phone = number
            fields.append('secondary_phone')
            filled['secondary_phone'] = number
        else:
            notes.append(number)
        if form:
            known.add(form)
    if notes:
        keep.notes = (keep.notes + '\n' if keep.notes else '') + 'Also reached on: ' + ', '.join(notes)
        fields.append('notes')

    for name in FILLABLE:
        if hasattr(keep, name) and not getattr(keep, name) and getattr(dup, name, None):
            setattr(keep, name, getattr(dup, name))
            fields.append(name)
            filled[name] = str(getattr(dup, name))
    if dup.notes:
        keep.notes = (keep.notes + '\n' if keep.notes else '') + dup.notes
        fields.append('notes')

    keep.visit_count = (keep.visit_count or 0) + (dup.visit_count or 0)
    keep.total_spend = (keep.total_spend or Decimal('0')) + (dup.total_spend or Decimal('0'))
    fields += ['visit_count', 'total_spend']

    CustomerMerge.objects.create(into=keep, merged_pk=dup.pk, snapshot=snapshot,
                                 moved=moved, filled=filled, reason=reason)
    dup.delete()
    keep.save(update_fields=sorted(set(fields)))
    return moved, filled


class Command(BaseCommand):
    help = 'Merge customers who are plainly the same person.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, apply=False, **options):
        pairs = find_pairs()
        for keep, other, number in getattr(find_pairs, 'companies', []):
            self.stdout.write(f'  possibly a person and their company, left as two: #{keep.pk} {keep.full_name!r} '
                              f'({keep.customer_type}) and #{other.pk} {other.full_name!r} ({other.customer_type}), on {number}')
        if not pairs:
            self.stdout.write('Nothing to merge.')
            return
        done = 0
        for keep, dup, number in pairs:
            head = (f'#{dup.pk} {dup.full_name!r} (made {dup.created_at:%d %b %Y}) into '
                    f'#{keep.pk} {keep.full_name!r} (made {keep.created_at:%d %b %Y}), both on {number}')
            if (dup.wallet_balance or 0) != 0:
                self.stdout.write(f'  NOT merging {head}: the newer one holds a wallet balance')
                continue
            if not apply:
                self.stdout.write(f'  would merge {head}')
                continue
            moved, filled = merge(keep, dup, f'same number {number}, names agree')
            what = ', '.join(f'{k.split(".")[-2]}: {len(v)}' for k, v in moved.items()) or 'nothing pointing at it'
            self.stdout.write(f'  merged {head}; moved {what}; filled {", ".join(filled) or "nothing"}')
            done += 1
        if apply:
            self.stdout.write(self.style.SUCCESS(f'Merged {done}.'))