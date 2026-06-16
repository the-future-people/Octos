"""
Analytics signal handlers.

These handlers listen to signals from operational apps and write
AuditEvent records. They are the single point of entry for all
audit data — no other code should write AuditEvents directly.

Rules:
- Handlers must never raise exceptions that bubble up to the caller.
  Wrap everything in try/except and log failures silently.
- Handlers must be fast — no heavy computation here.
  Heavy work goes to Celery tasks triggered from here.
- Handlers must be idempotent — safe to call multiple times
  with the same data (e.g. on retry).

Wired in: apps/analytics/apps.py → ready() method.
"""

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def _write_event(
    event_type,
    severity   = 'INFO',
    user       = None,
    branch     = None,
    session    = None,
    entity_type = '',
    entity_id  = None,
    metadata   = None,
    timestamp  = None,
):
    """
    Internal helper — creates an AuditEvent record.
    Never raises. Returns the event or None on failure.
    """
    try:
        from apps.analytics.models import AuditEvent
        return AuditEvent.objects.create(
            event_type  = event_type,
            severity    = severity,
            user        = user,
            branch      = branch,
            session     = session,
            entity_type = entity_type,
            entity_id   = entity_id,
            metadata    = metadata or {},
            timestamp   = timestamp or timezone.now(),
        )
    except Exception as e:
        logger.error('AuditEvent write failed [%s]: %s', event_type, e, exc_info=True)
        return None


def _get_active_session(user):
    """Returns the most recent active UserSession for a user, or None."""
    try:
        from apps.analytics.models import UserSession
        return UserSession.objects.filter(
            user     = user,
            ended_at = None,
        ).order_by('-started_at').first()
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Auth handlers
# ─────────────────────────────────────────────────────────────────────────────

def on_user_logged_in(sender, request, user, **kwargs):
    """Fires on successful login."""
    try:
        branch = getattr(user, 'branch', None)
        _write_event(
            event_type  = 'LOGIN_SUCCESS',
            severity    = 'INFO',
            user        = user,
            branch      = branch,
            entity_type = 'CustomUser',
            entity_id   = user.pk,
            metadata    = {
                'email'      : user.email,
                'role'       : getattr(getattr(user, 'role', None), 'name', None),
                'branch_code': getattr(branch, 'code', None),
                'ip'         : _get_ip(request),
                'user_agent' : request.META.get('HTTP_USER_AGENT', '')[:200],
            },
        )
    except Exception as e:
        logger.error('on_user_logged_in failed: %s', e, exc_info=True)


def on_user_logged_out(sender, request, user, **kwargs):
    """Fires on logout. Closes active session."""
    if not user:
        return
    try:
        from apps.analytics.engines.session_engine import SessionEngine
        SessionEngine.close_session(user, reason='LOGOUT')

        _write_event(
            event_type  = 'LOGOUT',
            severity    = 'INFO',
            user        = user,
            branch      = getattr(user, 'branch', None),
            entity_type = 'CustomUser',
            entity_id   = user.pk,
            metadata    = {'email': user.email},
        )
    except Exception as e:
        logger.error('on_user_logged_out failed: %s', e, exc_info=True)


def on_login_failed(sender, credentials, request, **kwargs):
    """Fires on failed login attempt."""
    try:
        _write_event(
            event_type = 'LOGIN_FAILED',
            severity   = 'MEDIUM',
            metadata   = {
                'email'     : credentials.get('username', ''),
                'ip'        : _get_ip(request),
                'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200],
            },
        )
    except Exception as e:
        logger.error('on_login_failed failed: %s', e, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# DailySalesSheet handlers
# ─────────────────────────────────────────────────────────────────────────────

def on_sheet_saved(sender, instance, created, **kwargs):
    """Fires on DailySalesSheet save. Detects open and close events."""
    try:
        if created:
            _write_event(
                event_type  = 'SHEET_OPENED',
                severity    = 'INFO',
                user        = instance.opened_by,
                branch      = instance.branch,
                session     = _get_active_session(instance.opened_by) if instance.opened_by else None,
                entity_type = 'DailySalesSheet',
                entity_id   = instance.pk,
                metadata    = {
                    'date'       : str(instance.date),
                    'branch_code': instance.branch.code,
                    'opened_by'  : instance.opened_by.full_name if instance.opened_by else 'System',
                },
            )
            return

        # Detect status transitions on update
        # We check update_fields to avoid firing on every save
        update_fields = kwargs.get('update_fields') or []

        if 'status' in (update_fields or []) or not update_fields:
            if instance.status == 'CLOSED':
                _write_event(
                    event_type  = 'SHEET_CLOSED',
                    severity    = 'INFO',
                    user        = instance.closed_by,
                    branch      = instance.branch,
                    session     = _get_active_session(instance.closed_by) if instance.closed_by else None,
                    entity_type = 'DailySalesSheet',
                    entity_id   = instance.pk,
                    metadata    = {
                        'date'        : str(instance.date),
                        'branch_code' : instance.branch.code,
                        'closed_by'   : instance.closed_by.full_name if instance.closed_by else 'System',
                        'total_cash'  : str(instance.total_cash),
                        'total_momo'  : str(instance.total_momo),
                        'total_pos'   : str(instance.total_pos),
                    },
                )
                _trigger_daily_risk(instance)
                _snapshot_hourly(instance)

            elif instance.status == 'AUTO_CLOSED':
                _write_event(
                    event_type  = 'SHEET_AUTO_CLOSED',
                    severity    = 'MEDIUM',
                    branch      = instance.branch,
                    entity_type = 'DailySalesSheet',
                    entity_id   = instance.pk,
                    metadata    = {
                        'date'       : str(instance.date),
                        'branch_code': instance.branch.code,
                    },
                )
                _trigger_daily_risk(instance)
                _snapshot_hourly(instance)

    except Exception as e:
        logger.error('on_sheet_saved failed: %s', e, exc_info=True)


def _trigger_daily_risk(sheet):
    """Triggers the daily risk analysis Celery task for a closed sheet."""
    try:
        from apps.analytics.tasks.daily import analyse_daily_risk
        analyse_daily_risk.delay(sheet.pk)
    except Exception as e:
        logger.error('_trigger_daily_risk failed for sheet %s: %s', sheet.pk, e, exc_info=True)


def _snapshot_hourly(sheet):
    """
    Builds HourlySheetSnapshot records for a just-closed sheet.
    One record per hour slot (7–19) regardless of whether jobs occurred.
    Fetches historical weather from Open-Meteo for accuracy.
    Never raises — failure is logged silently.
    """
    try:
        from django.db.models import Count, Sum
        from django.db.models.functions import ExtractHour
        from apps.jobs.models import Job
        from apps.analytics.models import HourlySheetSnapshot

        branch = sheet.branch

        # Compute week of month (1–5)
        day = sheet.date.day
        week_of_month = (day - 1) // 7 + 1

        # Hourly job counts and revenue from completed jobs on this sheet
        hourly_qs = Job.objects.filter(
            daily_sheet = sheet,
            status      = 'COMPLETE',
        ).annotate(
            hour = ExtractHour('created_at'),
        ).values('hour').annotate(
            job_count = Count('id'),
            revenue   = Sum('amount_paid'),
        ).order_by('hour')

        hourly_data = {
            row['hour']: {
                'job_count': row['job_count'],
                'revenue':   float(row['revenue'] or 0),
            }
            for row in hourly_qs
        }

        # Fetch historical weather from Open-Meteo
        weather_by_hour = _fetch_historical_weather(
            lat  = float(branch.latitude)  if branch.latitude  else 5.6037,
            lng  = float(branch.longitude) if branch.longitude else -0.1870,
            date = sheet.date,
        )

        # Create one snapshot per hour slot 7–19
        snapshots = []
        for hour in range(7, 20):
            data      = hourly_data.get(hour, {'job_count': 0, 'revenue': 0.0})
            job_count = data['job_count']
            revenue   = data['revenue']
            avg_val   = round(revenue / job_count, 2) if job_count > 0 else 0.0
            weather   = weather_by_hour.get(hour, {})

            snapshots.append(HourlySheetSnapshot(
                daily_sheet       = sheet,
                branch            = branch,
                date              = sheet.date,
                weekday           = sheet.date.weekday(),
                week_of_month     = week_of_month,
                hour              = hour,
                job_count         = job_count,
                revenue           = revenue,
                avg_job_value     = avg_val,
                weather_condition = weather.get('condition', ''),
                precipitation_mm  = weather.get('precipitation_mm', 0),
            ))

        HourlySheetSnapshot.objects.bulk_create(snapshots, ignore_conflicts=True)
        logger.info(
            '_snapshot_hourly: created %d hourly snapshots for sheet %s',
            len(snapshots), sheet.pk,
        )

    except Exception as e:
        logger.error(
            '_snapshot_hourly failed for sheet %s: %s', sheet.pk, e, exc_info=True
        )


def _fetch_historical_weather(lat: float, lng: float, date) -> dict:
    """
    Fetches hourly precipitation data from Open-Meteo archive API.
    Returns dict of {hour: {condition, precipitation_mm}}.
    Falls back to empty dict on any failure — weather is optional signal.

    Open-Meteo archive: free, no API key, covers Ghana.
    """
    try:
        import urllib.request
        import json

        date_str = date.strftime('%Y-%m-%d')
        url = (
            f'https://archive-api.open-meteo.com/v1/archive'
            f'?latitude={lat}&longitude={lng}'
            f'&start_date={date_str}&end_date={date_str}'
            f'&hourly=precipitation,weathercode'
            f'&timezone=Africa%2FAccra'
        )

        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())

        hours        = data['hourly']['time']          # ['2026-06-16T00:00', ...]
        precip       = data['hourly']['precipitation']  # [0.0, 0.2, ...]
        weathercodes = data['hourly']['weathercode']    # [0, 2, 61, ...]

        def _condition(code: int, precip_mm: float) -> str:
            if precip_mm >= 5.0:  return 'heavy_rain'
            if precip_mm >= 0.5:  return 'light_rain'
            if code in range(51, 68): return 'light_rain'
            if code in range(71, 78): return 'harmattan'
            if code in range(1, 4):   return 'cloudy'
            return 'clear'

        result = {}
        for i, time_str in enumerate(hours):
            hour = int(time_str[11:13])  # extract HH from 'YYYY-MM-DDTHH:MM'
            if 7 <= hour <= 19:
                p = float(precip[i] or 0)
                result[hour] = {
                    'condition'       : _condition(weathercodes[i], p),
                    'precipitation_mm': round(p, 2),
                }
        return result

    except Exception as e:
        logger.warning('_fetch_historical_weather failed: %s', e)
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# CashierFloat handlers
# ─────────────────────────────────────────────────────────────────────────────

def on_float_saved(sender, instance, created, **kwargs):
    """Fires on CashierFloat save. Detects set, acknowledged, signed-off."""
    try:
        update_fields = list(kwargs.get('update_fields') or [])

        if created:
            _write_event(
                event_type  = 'FLOAT_SET',
                severity    = 'INFO',
                user        = instance.float_set_by,
                branch      = getattr(instance.daily_sheet, 'branch', None) if instance.daily_sheet else None,
                entity_type = 'CashierFloat',
                entity_id   = instance.pk,
                metadata    = {
                    'cashier'       : instance.cashier.full_name,
                    'cashier_id'    : instance.cashier.pk,
                    'opening_float' : str(instance.opening_float),
                    'set_by'        : instance.float_set_by.full_name if instance.float_set_by else '—',
                    'scheduled_date': str(instance.scheduled_date) if instance.scheduled_date else None,
                },
            )
            return

        if 'morning_acknowledged' in update_fields and instance.morning_acknowledged:
            _write_event(
                event_type  = 'FLOAT_ACKNOWLEDGED',
                severity    = 'INFO',
                user        = instance.cashier,
                branch      = getattr(instance.daily_sheet, 'branch', None) if instance.daily_sheet else None,
                session     = _get_active_session(instance.cashier),
                entity_type = 'CashierFloat',
                entity_id   = instance.pk,
                metadata    = {
                    'cashier'       : instance.cashier.full_name,
                    'opening_float' : str(instance.opening_float),
                    'acknowledged_at': instance.morning_acknowledged_at.isoformat()
                        if instance.morning_acknowledged_at else None,
                    'breakdown'     : instance.opening_denomination_breakdown,
                },
            )

        if 'is_signed_off' in update_fields and instance.is_signed_off:
            variance = float(instance.variance or 0)
            severity = 'INFO'
            if abs(variance) > 50:
                severity = 'HIGH'
            elif abs(variance) > 10:
                severity = 'MEDIUM'
            elif abs(variance) > 0:
                severity = 'LOW'

            _write_event(
                event_type  = 'FLOAT_SIGNED_OFF',
                severity    = severity,
                user        = instance.cashier,
                branch      = getattr(instance.daily_sheet, 'branch', None) if instance.daily_sheet else None,
                session     = _get_active_session(instance.cashier),
                entity_type = 'CashierFloat',
                entity_id   = instance.pk,
                metadata    = {
                    'cashier'       : instance.cashier.full_name,
                    'opening_float' : str(instance.opening_float),
                    'closing_cash'  : str(instance.closing_cash),
                    'expected_cash' : str(instance.expected_cash),
                    'variance'      : str(instance.variance),
                    'variance_notes': instance.variance_notes,
                    'signed_off_at' : instance.signed_off_at.isoformat()
                        if instance.signed_off_at else None,
                },
            )

            if abs(variance) > 0:
                _write_event(
                    event_type  = 'FLOAT_VARIANCE',
                    severity    = severity,
                    user        = instance.cashier,
                    branch      = getattr(instance.daily_sheet, 'branch', None) if instance.daily_sheet else None,
                    entity_type = 'CashierFloat',
                    entity_id   = instance.pk,
                    metadata    = {
                        'cashier'      : instance.cashier.full_name,
                        'variance'     : variance,
                        'expected_cash': str(instance.expected_cash),
                        'closing_cash' : str(instance.closing_cash),
                    },
                )

    except Exception as e:
        logger.error('on_float_saved failed: %s', e, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Job handlers
# ─────────────────────────────────────────────────────────────────────────────

def on_job_saved(sender, instance, created, **kwargs):
    """Fires on Job save. Detects creation and status changes."""
    try:
        update_fields = list(kwargs.get('update_fields') or [])

        if created:
            severity = 'INFO'
            event_type = 'JOB_CREATED'

            # Post-closing job — high signal
            if getattr(instance, 'is_post_closing', False):
                event_type = 'JOB_POST_CLOSING'
                severity   = 'HIGH'

            _write_event(
                event_type  = event_type,
                severity    = severity,
                user        = instance.intake_by,
                branch      = instance.branch,
                session     = _get_active_session(instance.intake_by) if instance.intake_by else None,
                entity_type = 'Job',
                entity_id   = instance.pk,
                metadata    = {
                    'job_number'    : instance.job_number,
                    'title'         : instance.title,
                    'job_type'      : instance.job_type,
                    'intake_channel': instance.intake_channel,
                    'customer'      : instance.customer.full_name if instance.customer else 'Walk-in',
                    'estimated_cost': str(instance.estimated_cost or 0),
                    'intake_by'     : instance.intake_by.full_name if instance.intake_by else '—',
                    'is_post_closing': getattr(instance, 'is_post_closing', False),
                    'post_closing_reason': getattr(instance, 'post_closing_reason', ''),
                },
            )
            return

        if 'status' in update_fields:
            if instance.status == 'CANCELLED':
                _write_event(
                    event_type  = 'JOB_VOIDED',
                    severity    = 'MEDIUM',
                    user        = instance.intake_by,
                    branch      = instance.branch,
                    entity_type = 'Job',
                    entity_id   = instance.pk,
                    metadata    = {
                        'job_number': instance.job_number,
                        'title'     : instance.title,
                        'status'    : instance.status,
                    },
                )
            else:
                _write_event(
                    event_type  = 'JOB_STATUS_CHANGED',
                    severity    = 'INFO',
                    user        = instance.intake_by,
                    branch      = instance.branch,
                    entity_type = 'Job',
                    entity_id   = instance.pk,
                    metadata    = {
                        'job_number': instance.job_number,
                        'status'    : instance.status,
                    },
                )

    except Exception as e:
        logger.error('on_job_saved failed: %s', e, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Receipt (Payment) handlers
# ─────────────────────────────────────────────────────────────────────────────

def on_receipt_saved(sender, instance, created, **kwargs):
    """Fires on Receipt creation — payment confirmed."""
    if not created:
        return
    try:
        amount = float(instance.amount_paid or 0)
        severity = 'INFO'
        if amount > 1000:
            severity = 'LOW'  # Flag high single payments for review

        _write_event(
            event_type  = 'PAYMENT_CONFIRMED',
            severity    = severity,
            user        = instance.cashier,
            branch      = getattr(instance.daily_sheet, 'branch', None) if instance.daily_sheet else None,
            session     = _get_active_session(instance.cashier) if instance.cashier else None,
            entity_type = 'Receipt',
            entity_id   = instance.pk,
            metadata    = {
                'receipt_number' : instance.receipt_number,
                'job_number'     : instance.job.job_number if instance.job else '—',
                'amount_paid'    : amount,
                'payment_method' : instance.payment_method,
                'cashier'        : instance.cashier.full_name if instance.cashier else '—',
                'customer'       : instance.job.customer.full_name
                    if instance.job and instance.job.customer else 'Walk-in',
                'momo_reference' : getattr(instance, 'momo_reference', ''),
                'pos_approval'   : getattr(instance, 'pos_approval_code', ''),
            },
        )
    except Exception as e:
        logger.error('on_receipt_saved failed: %s', e, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# MonthlyClose handlers
# ─────────────────────────────────────────────────────────────────────────────

def on_monthly_close_saved(sender, instance, created, **kwargs):
    """Fires on MonthlyClose status transitions."""
    if created:
        return
    try:
        update_fields = list(kwargs.get('update_fields') or [])
        if 'status' not in (update_fields or []) and update_fields:
            return

        status_event_map = {
            'SUBMITTED'         : ('MONTHLY_SUBMITTED',       'INFO'),
            'FINANCE_REVIEWING' : ('MONTHLY_FINANCE_REVIEW',  'INFO'),
            'NEEDS_CLARIFICATION': ('MONTHLY_CLARIFICATION',  'MEDIUM'),
            'RESUBMITTED'       : ('MONTHLY_RESUBMITTED',     'INFO'),
            'ENDORSED'          : ('MONTHLY_ENDORSED',        'INFO'),
            'REJECTED'          : ('MONTHLY_REJECTED',        'HIGH'),
            'LOCKED'            : ('MONTHLY_LOCKED',          'INFO'),
        }

        event_info = status_event_map.get(instance.status)
        if not event_info:
            return

        event_type, severity = event_info

        _write_event(
            event_type  = event_type,
            severity    = severity,
            user        = instance.submitted_by,
            branch      = instance.branch,
            entity_type = 'MonthlyClose',
            entity_id   = instance.pk,
            metadata    = {
                'month'       : instance.month,
                'year'        : instance.year,
                'month_name'  : instance.month_name,
                'branch_code' : instance.branch.code,
                'status'      : instance.status,
                'submitted_by': instance.submitted_by.full_name if instance.submitted_by else '—',
                'endorsed_by' : instance.endorsed_by.full_name if instance.endorsed_by else None,
                'rejected_by' : instance.rejected_by.full_name if instance.rejected_by else None,
            },
        )

        # On submission, trigger MonthlyCloseSummary creation
        if instance.status == 'SUBMITTED':
            _trigger_monthly_summary(instance)

    except Exception as e:
        logger.error('on_monthly_close_saved failed: %s', e, exc_info=True)


def _trigger_monthly_summary(monthly_close):
    """Triggers the monthly summary compilation Celery task."""
    try:
        from apps.analytics.tasks.monthly import compile_monthly_summary
        compile_monthly_summary.delay(monthly_close.pk)
    except Exception as e:
        logger.error(
            '_trigger_monthly_summary failed for close %s: %s',
            monthly_close.pk, e, exc_info=True
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_ip(request):
    """Extract real IP from request, handling proxies."""
    if not request:
        return None
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')

def on_weekly_report_saved(sender, instance, created, **kwargs):
    """Fires on WeeklyReport save. Triggers weekly risk on LOCKED."""
    if created:
        return
    try:
        update_fields = list(kwargs.get('update_fields') or [])
        if 'status' not in (update_fields or []) and update_fields:
            return
        if instance.status == 'LOCKED':
            from apps.analytics.tasks.weekly import compute_weekly_risk
            compute_weekly_risk.delay(instance.pk)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error('on_weekly_report_saved failed: %s', e, exc_info=True)