"""
SessionEngine — manages UserSession lifecycle.

Called by:
- API view (SessionStartView) on portal load
- API view (SessionHeartbeatView) every 60s from frontend
- API view (SessionEventView) for critical-action tab switches
- Signal handler (on_user_logged_out) on logout

Design:
- One active session per user at a time (ended_at=None)
- Heartbeat updates last_seen_at and recomputes durations
- Session auto-closes if last_seen_at > TIMEOUT_MINUTES ago
- Critical-action tab switches increment critical_action_switches counter
"""

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
TIMEOUT_MINUTES    = 15   # Session times out after 15min of no heartbeat
IDLE_THRESHOLD_MIN = 5    # User considered idle after 5min without heartbeat


class SessionEngine:

    @classmethod
    def start_session(cls, user, portal, ip_address=None, user_agent=''):
        """
        Start a new session for a user.
        Closes any existing active session first.
        Returns the new UserSession.
        """
        from apps.analytics.models import UserSession

        try:
            # Close any existing active session
            cls.close_session(user, reason='NEW_SESSION')

            # Determine branch
            branch = getattr(user, 'branch', None)

            now = timezone.now()
            session = UserSession.objects.create(
                user        = user,
                branch      = branch,
                portal      = portal,
                started_at  = now,
                last_seen_at = now,
                ip_address  = ip_address,
                user_agent  = (user_agent or '')[:500],
            )
            logger.info(
                'Session started: user=%s portal=%s session=%s',
                user.pk, portal, session.pk
            )
            return session

        except Exception as e:
            logger.error('SessionEngine.start_session failed: %s', e, exc_info=True)
            return None

    @classmethod
    def heartbeat(cls, session_id, user):
        """
        Update last_seen_at and recompute durations.
        Called every 60s by frontend.
        Returns updated session or None.
        """
        from apps.analytics.models import UserSession

        try:
            session = UserSession.objects.get(pk=session_id, user=user, ended_at=None)
        except UserSession.DoesNotExist:
            logger.warning(
                'SessionEngine.heartbeat: session %s not found for user %s',
                session_id, user.pk
            )
            return None

        try:
            now      = timezone.now()
            previous = session.last_seen_at

            # Time since last heartbeat
            gap_seconds = int((now - previous).total_seconds())

            # If gap > IDLE_THRESHOLD, count as idle period
            idle_threshold_seconds = IDLE_THRESHOLD_MIN * 60
            if gap_seconds > idle_threshold_seconds:
                session.idle_count            += 1
                session.idle_duration_seconds += gap_seconds
            else:
                session.active_duration_seconds += gap_seconds

            session.total_duration_seconds = int(
                (now - session.started_at).total_seconds()
            )
            session.last_seen_at = now
            session.save(update_fields=[
                'last_seen_at',
                'total_duration_seconds',
                'active_duration_seconds',
                'idle_duration_seconds',
                'idle_count',
            ])
            return session

        except Exception as e:
            logger.error('SessionEngine.heartbeat failed: %s', e, exc_info=True)
            return None

    @classmethod
    def record_critical_switch(cls, session_id, user, action_context=''):
        """
        Record a tab switch during a critical action.
        Only called for high-signal events:
        - Payment confirmation modal open
        - EOD sign-off wizard open
        
        Returns updated session or None.
        """
        from apps.analytics.models import UserSession, AuditEvent

        try:
            session = UserSession.objects.get(pk=session_id, user=user, ended_at=None)
        except UserSession.DoesNotExist:
            return None

        try:
            session.critical_action_switches += 1
            session.save(update_fields=['critical_action_switches'])

            # Write AuditEvent for this specific switch
            AuditEvent.objects.create(
                event_type  = AuditEvent.TAB_SWITCH_CRITICAL,
                severity    = AuditEvent.MEDIUM,
                user        = user,
                branch      = session.branch,
                session     = session,
                entity_type = 'UserSession',
                entity_id   = session.pk,
                metadata    = {
                    'action_context': action_context,
                    'total_switches': session.critical_action_switches,
                    'portal'        : session.portal,
                },
                timestamp   = timezone.now(),
            )
            return session

        except Exception as e:
            logger.error('SessionEngine.record_critical_switch failed: %s', e, exc_info=True)
            return None

    @classmethod
    def close_session(cls, user, reason='LOGOUT'):
        """
        Close the active session for a user.
        Computes final durations and marks ended_at.
        Returns closed session or None.
        """
        from apps.analytics.models import UserSession

        try:
            session = UserSession.objects.filter(
                user     = user,
                ended_at = None,
            ).order_by('-started_at').first()

            if not session:
                return None

            now = timezone.now()
            session.ended_at               = now
            session.total_duration_seconds = int(
                (now - session.started_at).total_seconds()
            )
            session.save(update_fields=[
                'ended_at',
                'total_duration_seconds',
            ])

            logger.info(
                'Session closed: user=%s session=%s reason=%s duration=%ss',
                user.pk, session.pk, reason, session.total_duration_seconds
            )
            return session

        except Exception as e:
            logger.error('SessionEngine.close_session failed: %s', e, exc_info=True)
            return None

    @classmethod
    def timeout_stale_sessions(cls):
        """
        Close sessions where last_seen_at > TIMEOUT_MINUTES ago.
        Called by Celery beat every 15 minutes.
        """
        from apps.analytics.models import UserSession

        cutoff = timezone.now() - timedelta(minutes=TIMEOUT_MINUTES)
        stale  = UserSession.objects.filter(
            ended_at     = None,
            last_seen_at__lt = cutoff,
        )

        count = 0
        for session in stale:
            session.ended_at               = session.last_seen_at
            session.total_duration_seconds = int(
                (session.last_seen_at - session.started_at).total_seconds()
            )
            session.save(update_fields=['ended_at', 'total_duration_seconds'])
            count += 1

        if count:
            logger.info('SessionEngine: closed %d stale sessions', count)
        return count