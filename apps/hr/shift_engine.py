from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


class ShiftEngine:
    """
    Resolves the operational shift schedule for a branch and its roles.

    Responsibilities:
    - Find the active BranchShift for a branch on a given date
    - Compute role-specific lock times from ShiftRoleConfig
    - Use role_start_time / role_end_time when set, falling back to BranchShift times
    - Determine if branch is currently in post-closing window
    - Provide shift status for frontend display

    Rules:
    - Sunday never has a shift
    - BranchShift.days drives which days a shift applies
    - ShiftRoleConfig drives per-role times and buffer times
    - If no BranchShift found, falls back to safe defaults
    """

    # ── Safe fallback constants (used only if no BranchShift is configured) ──
    FALLBACK_START          = '07:30'
    FALLBACK_END            = '19:30'
    FALLBACK_ATTENDANT_LOCK = 0
    FALLBACK_CASHIER_LOCK   = 45
    FALLBACK_BM_AUTOCLOSE   = 60

    def __init__(self, branch) -> None:
        self.branch = branch

    # ── Core resolution ───────────────────────────────────────────

    def get_today_shift(self) -> Optional[object]:
        """
        Returns the active BranchShift for today, or None if not found.
        Sunday always returns None.
        """
        from apps.hr.models import BranchShift

        today = timezone.localdate()

        if today.weekday() == 6:
            return None

        shifts = BranchShift.objects.filter(
            branch    = self.branch,
            is_active = True,
        )

        for shift in shifts:
            if today.weekday() in shift.day_list:
                return shift

        return None

    def get_role_schedule(self, role_name: str, target_date: Optional[date] = None) -> dict:
        """
        Returns the full schedule for a given role today.

        Uses role_start_time / role_end_time from ShiftRoleConfig when set,
        falling back to BranchShift.start_time / end_time.

        Returns dict with:
            shift_name       : str
            shift_start      : datetime ISO (role-effective start)
            shift_end        : datetime ISO (role-effective end)
            job_lock_at      : datetime ISO
            signoff_at       : datetime ISO
            autoclose_at     : datetime ISO | None (BM only)
            is_open          : bool
            is_post_closing  : bool
            is_locked        : bool
            can_create_jobs  : bool
            can_signoff      : bool
            mins_to_end      : int
            lock_reason      : str | None
            using_fallback   : bool
        """
        if target_date is None:
            target_date = timezone.localdate()

        now   = timezone.now()
        shift = self.get_today_shift()

        if shift:
            config = self._get_role_config(shift, role_name)

            # Use role-specific times if set, else fall back to shift times
            effective_start = config['role_start_time'] or shift.start_time
            effective_end   = config['role_end_time']   or shift.end_time

            start = self._make_aware(target_date, effective_start)
            end   = self._make_aware(target_date, effective_end)

            job_lock_at  = end + timedelta(minutes=config['job_lock_buffer'])
            signoff_at   = end + timedelta(minutes=config['signoff_buffer'])
            autoclose_at = (
                end + timedelta(minutes=config['autoclose_buffer'])
                if config['autoclose_buffer'] is not None
                else None
            )
            shift_name     = shift.name
            using_fallback = False
        else:
            # Fallback — no shift configured
            start        = self._make_aware(target_date, self._parse_time(self.FALLBACK_START))
            end          = self._make_aware(target_date, self._parse_time(self.FALLBACK_END))
            lock_buffer  = {
                'ATTENDANT'     : self.FALLBACK_ATTENDANT_LOCK,
                'CASHIER'       : self.FALLBACK_CASHIER_LOCK,
                'BRANCH_MANAGER': self.FALLBACK_BM_AUTOCLOSE,
            }.get(role_name, 0)
            job_lock_at   = end + timedelta(minutes=lock_buffer)
            signoff_at    = end + timedelta(minutes=lock_buffer)
            autoclose_at  = (
                end + timedelta(minutes=self.FALLBACK_BM_AUTOCLOSE)
                if role_name == 'BRANCH_MANAGER' else None
            )
            shift_name     = 'Default'
            using_fallback = True

        mins_to_end     = int((end - now).total_seconds() / 60)
        is_open         = start <= now < end
        is_post_closing = end <= now < job_lock_at
        is_locked       = now >= job_lock_at
        can_create_jobs = now < job_lock_at
        can_signoff     = now >= end

        lock_reason = None
        if is_post_closing:
            mins_left = int((job_lock_at - now).total_seconds() / 60)
            lock_reason = (
                f"Branch closed at {end.strftime('%I:%M %p')}. "
                f"You have {mins_left} minute(s) to complete current work."
            )
        elif is_locked:
            lock_reason = f"Shift ended at {end.strftime('%I:%M %p')}. Portal is locked."

        return {
            'shift_name'      : shift_name,
            'shift_start'     : start.isoformat(),
            'shift_end'       : end.isoformat(),
            'job_lock_at'     : job_lock_at.isoformat(),
            'signoff_at'      : signoff_at.isoformat(),
            'autoclose_at'    : autoclose_at.isoformat() if autoclose_at else None,
            'is_open'         : is_open,
            'is_post_closing' : is_post_closing,
            'is_locked'       : is_locked,
            'can_create_jobs' : can_create_jobs,
            'can_signoff'     : can_signoff,
            'mins_to_end'     : mins_to_end,
            'lock_reason'     : lock_reason,
            'using_fallback'  : using_fallback,
        }

    def get_branch_status(self) -> dict:
        """
        Returns the overall branch operational status.
        Uses BranchShift times directly (not role-specific).
        """
        today = timezone.localdate()

        if today.weekday() == 6:
            return {
                'is_open'      : False,
                'is_sunday'    : True,
                'shift_name'   : None,
                'shift_start'  : None,
                'shift_end'    : None,
                'status_label' : 'Closed — Sunday',
            }

        shift = self.get_today_shift()
        if not shift:
            return {
                'is_open'      : False,
                'is_sunday'    : False,
                'shift_name'   : None,
                'shift_start'  : None,
                'shift_end'    : None,
                'status_label' : 'No shift configured for today',
            }

        now   = timezone.now()
        start = self._make_aware(today, shift.start_time)
        end   = self._make_aware(today, shift.end_time)
        is_open = start <= now < end

        return {
            'is_open'      : is_open,
            'is_sunday'    : False,
            'shift_name'   : shift.name,
            'shift_start'  : start.isoformat(),
            'shift_end'    : end.isoformat(),
            'status_label' : 'Open' if is_open else (
                'Not started yet' if now < start else 'Closed for the day'
            ),
        }

    # ── Employee-level resolution ─────────────────────────────────

    def get_employee_shift_end(self, employee) -> Optional[datetime]:
        """
        Returns the effective shift end for a specific employee today.
        Checks ShiftOverride first, then EmployeeShift base record.
        Falls back to BranchShift end_time if no HR record found.
        """
        from apps.hr.models import EmployeeShift, ShiftOverride

        today = timezone.localdate()

        override = ShiftOverride.objects.filter(
            employee    = employee,
            date        = today,
        ).exclude(
            override_type = ShiftOverride.ABSENCE,
        ).order_by('-created_at').first()

        if override and override.override_end:
            return self._make_aware(today, override.override_end)

        base = EmployeeShift.objects.filter(
            employee    = employee,
            day_of_week = today.weekday(),
            is_active   = True,
        ).first()

        if base:
            return self._make_aware(today, base.end_time)

        shift = self.get_today_shift()
        if shift:
            return self._make_aware(today, shift.end_time)

        return None

    # ── Internal helpers ──────────────────────────────────────────

    def _get_role_config(self, shift, role_name: str) -> dict:
        """
        Returns role config dict for a shift including effective times.
        Falls back to safe defaults if ShiftRoleConfig not found.
        role_start_time / role_end_time are None when not set —
        caller falls back to BranchShift times in that case.
        """
        from apps.hr.models import ShiftRoleConfig

        DEFAULTS = {
            'ATTENDANT'     : {'job_lock_buffer': 0,  'signoff_buffer': 30, 'autoclose_buffer': None},
            'CASHIER'       : {'job_lock_buffer': 45, 'signoff_buffer': 45, 'autoclose_buffer': None},
            'BRANCH_MANAGER': {'job_lock_buffer': 60, 'signoff_buffer': 60, 'autoclose_buffer': 60},
        }

        try:
            config = ShiftRoleConfig.objects.get(shift=shift, role_name=role_name)
            return {
                'role_start_time' : config.role_start_time,
                'role_end_time'   : config.role_end_time,
                'job_lock_buffer' : config.job_lock_buffer,
                'signoff_buffer'  : config.signoff_buffer,
                'autoclose_buffer': config.autoclose_buffer,
            }
        except ShiftRoleConfig.DoesNotExist:
            defaults = DEFAULTS.get(role_name, DEFAULTS['ATTENDANT'])
            return {
                'role_start_time' : None,
                'role_end_time'   : None,
                **defaults,
            }

    def _make_aware(self, target_date: date, t) -> datetime:
        naive = datetime.combine(target_date, t)
        return timezone.make_aware(naive)

    @staticmethod
    def _parse_time(time_str: str):
        from datetime import time
        h, m = time_str.split(':')
        return time(int(h), int(m))