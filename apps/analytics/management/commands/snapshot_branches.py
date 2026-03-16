"""
Management command to compute and save daily branch snapshots.

Run manually:
    python manage.py snapshot_branches

Schedule via cron (daily at midnight):
    0 0 * * * /path/to/venv/bin/python manage.py snapshot_branches
"""

from django.core.management.base import BaseCommand

from apps.organization.models import Branch
from apps.analytics.services import compute_snapshot


class Command(BaseCommand):
    help = 'Compute and save daily analytics snapshots for all active branches.'

    def handle(self, *args, **options):
        branches = Branch.objects.filter(is_active=True)
        total    = branches.count()

        self.stdout.write(f'Snapshotting {total} branches...')

        success = 0
        failed  = 0

        for branch in branches:
            try:
                snapshot = compute_snapshot(branch)
                self.stdout.write(
                    self.style.SUCCESS(f'  ✓ {branch.name} | jobs={snapshot.total_jobs}')
                )
                success += 1
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(f'  ✗ {branch.name} | {exc}')
                )
                failed += 1

        self.stdout.write(f'\nDone. {success} succeeded, {failed} failed.')