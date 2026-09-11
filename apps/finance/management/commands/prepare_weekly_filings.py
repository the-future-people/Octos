"""
Builds the draft weekly filing for every branch.

Runs Saturday evening, and the manager submits it. The draft is only a
convenience: it exists so the figures are already aggregated when someone
opens the page, and nothing is locked by it.

It is deliberately not the guarantee. This system has a history of
scheduled work that was received and discarded, or that ran a stale build
for two months while reporting green — so the Monday check in the branch
manager's portal prepares the week itself if this never ran. Saturday
being missed must cost nothing.
"""

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Prepare (not submit) the current weekly filing for every active branch.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            help='Prepare the week containing this date (YYYY-MM-DD) instead of today.',
        )

    def handle(self, *args, **options):
        from datetime import date as date_cls
        from apps.finance.services.weekly_report_service import WeeklyReportService
        from apps.organization.models import Branch

        if options.get('date'):
            target = date_cls.fromisoformat(options['date'])
        else:
            target = timezone.localdate()

        # Sunday has no trading and no sheets, so there is nothing to
        # aggregate and a draft would be an empty record.
        if target.weekday() == 6:
            self.stdout.write('Sunday — nothing to prepare.')
            return

        prepared = 0
        for branch in Branch.objects.filter(is_active=True):
            try:
                report, created = WeeklyReportService.prepare(branch, today=target)
            except Exception:
                # One branch failing must not stop the rest. A branch
                # without a draft is recoverable on Monday; a task that
                # died halfway leaves every branch after it unprepared.
                logger.exception(
                    'prepare_weekly_filings: failed for branch %s', branch.code,
                )
                self.stdout.write(self.style.ERROR(f'  {branch.code} — failed'))
                continue

            if (report.status == report.Status.DRAFT
                    and not report.total_jobs_created
                    and not report.total_collected):
                report.delete()
                continue

            prepared += 1
            self.stdout.write(
                f'  {branch.code} — week {report.week_number} '
                f'({report.date_from} to {report.date_to}) '
                f'{"created" if created else "refreshed"}, '
                f'{report.total_jobs_created} jobs'
            )

        self.stdout.write(self.style.SUCCESS(
            f'weekly filings — {prepared} branch(es) prepared'
        ))