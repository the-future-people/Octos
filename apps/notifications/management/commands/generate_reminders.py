import logging
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)

# 5-minute buckets within the 30-minute pre-close window.
# Bucket 0 = 30-25 min remaining, ..., bucket 5 = 5-0 min remaining.
BUCKET_SIZE_MINUTES = 5
WINDOW_MINUTES = 30


class Command(BaseCommand):
    """
    Generates interruptive reminder Notifications on a schedule, replacing
    the previous scattered frontend-only ShiftEndingModal / GenericReminderNudge.

    Modes:
      shift       — 30-min-before-close reminder, re-surfacing every 5 min,
                    for CASHIER, ATTENDANT, BRANCH_MANAGER. Stops once the
                    role's shift_end has passed, or (Cashier only) once
                    signed off early.
      checkpoint  — due, unacknowledged TaskCheckpoints become PIN-gated
                    reminders (personal_notes privacy preserved — message
                    stays generic, real content never touches Notification).

    Idempotent via dedupe_key + unique_nonblank_dedupe_key constraint —
    safe to run frequently (every 1 minute via Celery Beat) without ever
    producing duplicate reminders.

    Usage:
      python manage.py generate_reminders --type shift
      python manage.py generate_reminders --type checkpoint
    """

    help = 'Generate interruptive shift-ending and task-checkpoint reminders'

    def add_arguments(self, parser):
        parser.add_argument(
            '--type',
            choices=['shift', 'checkpoint'],
            required=True,
        )

    def handle(self, *args, **options):
        reminder_type = options['type']
        if reminder_type == 'shift':
            self._run_shift()
        elif reminder_type == 'checkpoint':
            self._run_checkpoint()

    # ── Shift-ending reminders ──────────────────────────────────

    def _run_shift(self):
        from apps.accounts.models import CustomUser
        from apps.finance.models import CashierFloat
        from apps.hr.shift_engine import ShiftEngine as HRShiftEngine
        from apps.notifications.models import Notification
        from apps.notifications.services import notify

        today = timezone.localdate()
        now   = timezone.now()
        created = 0

        # Sunday and holidays are handled entirely by PortalLockedOverlay
        # client-side — no shift exists to be "ending" on those days.
        if today.weekday() == 6:
            self.stdout.write('Sunday — skipping shift reminders entirely.')
            return

        users = CustomUser.objects.filter(
            is_active=True,
            role__name__in=['ATTENDANT', 'CASHIER', 'BRANCH_MANAGER'],
            branch__isnull=False,
        ).select_related('role', 'branch')

        for user in users:
            role_name = user.role.name
            try:
                schedule = HRShiftEngine(user.branch).get_role_schedule(role_name, target_date=today)
            except Exception:
                logger.exception(
                    'generate_reminders shift: failed to get schedule for user %s', user.pk
                )
                continue

            shift_end = datetime.fromisoformat(schedule['shift_end'])
            mins_remaining = int((shift_end - now).total_seconds() / 60)

            # Outside the 30-minute pre-close window entirely (too early
            # or already past shift_end) — nothing to create.
            if mins_remaining > WINDOW_MINUTES or mins_remaining < 0:
                continue

            # Cashier-only: stop early if already signed off, even
            # though shift_end hasn't technically passed yet.
            if role_name == 'CASHIER':
                already_signed_off = CashierFloat.objects.filter(
                    daily_sheet__branch=user.branch,
                    daily_sheet__date=today,
                    cashier=user,
                    is_signed_off=True,
                ).exists()
                if already_signed_off:
                    continue

            bucket = (WINDOW_MINUTES - mins_remaining) // BUCKET_SIZE_MINUTES
            dedupe_key = f"shift_ending-{user.pk}-{today.isoformat()}-{bucket}"

            _, was_created = Notification.objects.get_or_create(
                dedupe_key=dedupe_key,
                defaults=dict(
                    recipient=user,
                    verb=Notification.Verb.SHIFT_ENDING,
                    message=(
                        f"Your shift ends at {shift_end.strftime('%I:%M %p')}. "
                        f"{mins_remaining} minute(s) remaining."
                    ),
                    category=Notification.Category.REMINDER,
                    display_mode=Notification.DisplayMode.INTERRUPTIVE,
                    requires_pin=False,
                ),
            )
            if was_created:
                created += 1

        self.stdout.write(self.style.SUCCESS(f'shift reminders — {created} created'))

    # ── Personal task checkpoint reminders ──────────────────────

    def _run_checkpoint(self):
        from django.contrib.contenttypes.models import ContentType
        from apps.personal_notes.models import TaskCheckpoint
        from apps.notifications.models import Notification

        now = timezone.now()
        created = 0

        due = TaskCheckpoint.objects.filter(
            scheduled_at__lte=now,
            acknowledged=False,
        ).select_related('note', 'note__owner')

        checkpoint_ct = ContentType.objects.get_for_model(TaskCheckpoint)

        for checkpoint in due:
            dedupe_key = f"task_checkpoint-{checkpoint.pk}"

            _, was_created = Notification.objects.get_or_create(
                dedupe_key=dedupe_key,
                defaults=dict(
                    recipient=checkpoint.note.owner,
                    verb=Notification.Verb.TASK_CHECKPOINT,
                    message='A private note needs attention.',
                    category=Notification.Category.REMINDER,
                    display_mode=Notification.DisplayMode.INTERRUPTIVE,
                    requires_pin=True,
                    content_type=checkpoint_ct,
                    object_id=checkpoint.pk,
                ),
            )
            if was_created:
                created += 1

        self.stdout.write(self.style.SUCCESS(f'checkpoint reminders — {created} created'))