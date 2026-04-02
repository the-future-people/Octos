from django.apps import AppConfig

from apps.analytics.signals.handlers import on_weekly_report_saved


class AnalyticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'apps.analytics'
    label = 'analytics'

    def ready(self):
        """
        Connect all signal handlers.
        Called once when Django starts up.
        Import here to avoid circular imports at module load time.
        """
        from django.contrib.auth.signals import (
            user_logged_in,
            user_logged_out,
            user_login_failed,
        )
        from django.db.models.signals import post_save

        from apps.analytics.signals.handlers import (
            on_user_logged_in,
            on_user_logged_out,
            on_login_failed,
            on_sheet_saved,
            on_float_saved,
            on_job_saved,
            on_receipt_saved,
            on_monthly_close_saved,
        )

        # ── Auth signals ──────────────────────────────────────
        user_logged_in.connect(on_user_logged_in,  dispatch_uid='analytics_login_success')
        user_logged_out.connect(on_user_logged_out, dispatch_uid='analytics_logout')
        user_login_failed.connect(on_login_failed,  dispatch_uid='analytics_login_failed')

        # ── Operational signals ───────────────────────────────
        # Import models here to avoid AppRegistryNotReady
        from apps.finance.models import DailySalesSheet, CashierFloat, Receipt
        from apps.finance.models import MonthlyClose
        from apps.jobs.models import Job

        post_save.connect(
            on_sheet_saved,
            sender    = DailySalesSheet,
            dispatch_uid = 'analytics_sheet_saved',
        )
        post_save.connect(
            on_float_saved,
            sender    = CashierFloat,
            dispatch_uid = 'analytics_float_saved',
        )
        post_save.connect(
            on_job_saved,
            sender    = Job,
            dispatch_uid = 'analytics_job_saved',
        )
        post_save.connect(
            on_receipt_saved,
            sender    = Receipt,
            dispatch_uid = 'analytics_receipt_saved',
        )
        post_save.connect(
            on_monthly_close_saved,
            sender    = MonthlyClose,
            dispatch_uid = 'analytics_monthly_close_saved',
        )
        from apps.finance.models import WeeklyReport
        post_save.connect(
            on_weekly_report_saved,
            sender       = WeeklyReport,
            dispatch_uid = 'analytics_weekly_report_saved',
        )
        