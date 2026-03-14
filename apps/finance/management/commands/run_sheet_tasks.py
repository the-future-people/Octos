import logging
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Management command that handles all scheduled sheet tasks.

    Run modes:
      open       — Open sheets for all active branches (run at 5:00am daily)
      close      — Auto-close sheets past their BM close window (run every 15min)
      warn       — Check which branches are in warning window (run every 5min)

    Usage:
      python manage.py run_sheet_tasks open
      python manage.py run_sheet_tasks close
      python manage.py run_sheet_tasks warn

    Schedule on Windows Task Scheduler:
      5:00am daily  → run_sheet_tasks open
      Every 15min   → run_sheet_tasks close
      Every 5min    → run_sheet_tasks warn
    """

    help = 'Run scheduled daily sheet tasks — open, close, or warn'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            'mode',
            choices=['open', 'close', 'warn'],
            help='Task mode: open | close | warn',
        )

    def handle(self, *args, **options) -> None:
        mode = options['mode']

        if mode == 'open':
            self._run_open()
        elif mode == 'close':
            self._run_close()
        elif mode == 'warn':
            self._run_warn()

    # ── Open ──────────────────────────────────────────────────────

    def _run_open(self) -> None:
        """
        Open a daily sheet for every active branch.
        Skips Sundays automatically inside SheetEngine.
        Skips branches that already have an open sheet today.
        """
        from apps.organization.models import Branch
        from apps.finance.sheet_engine import SheetEngine

        today    = timezone.localdate()
        branches = Branch.objects.filter(is_active=True)
        opened   = 0
        skipped  = 0

        for branch in branches:
            try:
                sheet, created = SheetEngine(branch).open_sheet(
                    target_date=today,
                    opened_by=None,   # system open
                )
                if created:
                    opened += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  Opened sheet for {branch.code} — {today}'
                        )
                    )
                else:
                    skipped += 1
            except Exception as exc:
                logger.exception(
                    'run_sheet_tasks open: failed for branch %s', branch.code
                )
                self.stdout.write(
                    self.style.ERROR(
                        f'  ERROR opening sheet for {branch.code}: {exc}'
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'open complete — {opened} opened, {skipped} already existed'
            )
        )

    # ── Close ─────────────────────────────────────────────────────

    def _run_close(self) -> None:
        """
        Auto-close any open sheet whose BM close window has passed.
        BM close window = closing_time + BM_AUTOCLOSE_AFTER minutes.
        """
        from apps.finance.models import DailySalesSheet
        from apps.finance.sheet_engine import SheetEngine
        from datetime import datetime, timedelta

        now    = timezone.now()
        today  = timezone.localdate()
        closed = 0

        open_sheets = DailySalesSheet.objects.filter(
            date=today,
            status=DailySalesSheet.Status.OPEN,
        ).select_related('branch')

        for sheet in open_sheets:
            branch       = sheet.branch
            closing_time = branch.closing_time
            naive_close  = datetime.combine(today, closing_time)
            aware_close  = timezone.make_aware(naive_close)
            autoclose_at = aware_close + timedelta(
                minutes=SheetEngine.BM_AUTOCLOSE_AFTER
            )

            if now >= autoclose_at:
                try:
                    engine = SheetEngine(branch)
                    engine.close_sheet(sheet, closed_by=None, auto=True)
                    closed += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  Auto-closed sheet for {branch.code}'
                        )
                    )
                except Exception as exc:
                    logger.exception(
                        'run_sheet_tasks close: failed for branch %s',
                        branch.code,
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f'  ERROR closing sheet for {branch.code}: {exc}'
                        )
                    )

        self.stdout.write(
            self.style.SUCCESS(f'close complete — {closed} sheet(s) auto-closed')
        )

    # ── Warn ──────────────────────────────────────────────────────

    def _run_warn(self) -> None:
        """
        Check which branches are entering the warning window
        and fire a notification to all active staff at those branches.
        Warning window = closing_time - WARNING_BEFORE_CLOSE minutes.
        """
        from apps.finance.models import DailySalesSheet
        from apps.finance.sheet_engine import SheetEngine
        from apps.accounts.models import CustomUser
        from datetime import datetime, timedelta

        now   = timezone.now()
        today = timezone.localdate()

        open_sheets = DailySalesSheet.objects.filter(
            date=today,
            status=DailySalesSheet.Status.OPEN,
        ).select_related('branch')

        warned = 0

        for sheet in open_sheets:
            branch       = sheet.branch
            closing_time = branch.closing_time
            naive_close  = datetime.combine(today, closing_time)
            aware_close  = timezone.make_aware(naive_close)
            warn_at      = aware_close - timedelta(
                minutes=SheetEngine.WARNING_BEFORE_CLOSE
            )

            # Only fire once — within the 5-minute check window
            window_end = warn_at + timedelta(minutes=5)

            if warn_at <= now < window_end:
                try:
                    self._send_warning(branch, sheet, aware_close)
                    warned += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'  Warning sent for {branch.code}'
                        )
                    )
                except Exception as exc:
                    logger.exception(
                        'run_sheet_tasks warn: failed for branch %s',
                        branch.code,
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f'  ERROR sending warning for {branch.code}: {exc}'
                        )
                    )

        self.stdout.write(
            self.style.SUCCESS(f'warn complete — {warned} branch(es) warned')
        )

    def _send_warning(self, branch, sheet, closing_at) -> None:
        """
        Send end-of-day warning notification to all active staff
        at the branch via the notifications system.
        """
        try:
            from apps.notifications.services import notify
            from apps.accounts.models import CustomUser

            staff = CustomUser.objects.filter(
                branch=branch,
                is_active=True,
            )

            close_str = closing_at.strftime('%I:%M %p')

            for member in staff:
                notify(
                    recipient=member,
                    verb='END_OF_DAY_WARNING',
                    message=(
                        f"Branch closes at {close_str}. "
                        f"Complete all pending work and payments before close."
                    ),
                    target_id=sheet.pk,
                    target_type='DailySalesSheet',
                )
        except Exception:
            logger.exception(
                'run_sheet_tasks warn: notification failed for branch %s',
                branch.code,
            )