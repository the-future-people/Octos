from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Expire drafts older than 3 days — marks them CANCELLED and records abandoned_at'

    def handle(self, *args, **options):
        from apps.jobs.models import Job

        now     = timezone.now()
        expired = Job.objects.filter(
            status           = Job.DRAFT,
            draft_expires_at__lte = now,
        )

        count = expired.count()
        if count == 0:
            self.stdout.write('No drafts to expire.')
            return

        expired.update(
            status       = Job.CANCELLED,
            abandoned_at = now,
        )

        self.stdout.write(
            self.style.SUCCESS(f'Expired {count} draft(s).')
        )