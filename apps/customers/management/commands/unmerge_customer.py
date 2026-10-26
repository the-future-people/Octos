"""
Undo one customer merge, exactly.

    python manage.py unmerge_customer 327           # shows what it would do
    python manage.py unmerge_customer 327 --apply   # does it

The number is the ID of the record that was merged away. From the merge
record's snapshot, that customer is recreated as it was, with the same
ID; everything that moved to the survivor moves back; the fields the
merge filled on the survivor are cleared, but only where they still hold
exactly what the merge put there (anything edited since is left alone
and listed); the merged visits and spend are taken back off. Then the
merge record goes, since it no longer describes anything that happened.
"""

from decimal import Decimal

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime


class Command(BaseCommand):
    help = 'Undo one customer merge, from its snapshot.'

    def add_arguments(self, parser):
        parser.add_argument('merged_pk', type=int)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, merged_pk, apply=False, **options):
        from apps.customers.models import CustomerMerge, CustomerProfile

        m = CustomerMerge.objects.filter(merged_pk=merged_pk).select_related('into').first()
        if m is None:
            raise CommandError(f'No merge of #{merged_pk} on record.')
        if CustomerProfile.objects.filter(pk=merged_pk).exists():
            raise CommandError(f'#{merged_pk} already exists again.')
        keep, snap = m.into, m.snapshot

        self.stdout.write(f'Undo: #{merged_pk} {snap.get("company_name") or ""} '
                          f'({snap.get("first_name")} {snap.get("last_name")}) back out of #{keep.pk} {keep.full_name!r}')
        for label, pks in m.moved.items():
            self.stdout.write(f'  move back {label}: {pks}')
        clear, kept = [], []
        for name, value in m.filled.items():
            now = getattr(keep, name, None)
            (clear if now is not None and str(now) == value else kept).append(name)
        self.stdout.write(f'  clear from #{keep.pk}: {", ".join(clear) or "nothing"}')
        if kept:
            self.stdout.write(f'  left as they are (changed since the merge): {", ".join(kept)}')
        if not apply:
            self.stdout.write('Dry run: nothing changed.')
            return

        with transaction.atomic():
            # The customer, as it was.
            restored = CustomerProfile(pk=merged_pk)
            for f in CustomerProfile._meta.concrete_fields:
                if f.primary_key or f.name not in snap:
                    continue
                raw = snap[f.name]
                if f.is_relation:
                    setattr(restored, f.attname, int(raw) if raw not in (None, '', 'None') else None)
                else:
                    setattr(restored, f.name, None if raw is None else f.to_python(raw))
            restored.save()
            created = parse_datetime(snap.get('created_at') or '')
            if created:
                CustomerProfile.objects.filter(pk=merged_pk).update(created_at=created)

            # What moved, back.
            for label, pks in m.moved.items():
                app_label, model_name, field = label.split('.')
                model = apps.get_model(app_label, model_name)
                model._default_manager.filter(pk__in=pks).update(**{field: restored})

            # The survivor, without what the merge gave it.
            keep = CustomerProfile.objects.select_for_update().get(pk=keep.pk)
            fields = []
            for name in clear:
                f = CustomerProfile._meta.get_field(name)
                setattr(keep, name, None if (f.is_relation or f.null) else '')
                fields.append(name)
            keep.visit_count = max(0, (keep.visit_count or 0) - int(snap.get('visit_count') or 0))
            keep.total_spend = max(Decimal('0'), (keep.total_spend or Decimal('0')) - Decimal(snap.get('total_spend') or '0'))
            fields += ['visit_count', 'total_spend']
            dup_notes = snap.get('notes') or ''
            if dup_notes and keep.notes and keep.notes.endswith(dup_notes):
                keep.notes = keep.notes[: -len(dup_notes)].rstrip('\n')
                fields.append('notes')
            keep.save(update_fields=sorted(set(fields)))
            m.delete()
        self.stdout.write(self.style.SUCCESS(f'#{merged_pk} is back, and #{keep.pk} is as it was.'))