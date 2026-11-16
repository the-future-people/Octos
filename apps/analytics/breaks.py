"""
Breaks (16 Nov 2026). After 30 minutes without a touch, the attendant's
portal asks "are you there?". "Taking a break" marks their session on break,
so the manager's On shift shows "On break" rather than idle; "I'm back" ends
it. A break past BREAK_ALERT_MINUTES tells the branch's Branch Manager, once.
"""
from datetime import timedelta

from django.utils import timezone

BREAK_ALERT_MINUTES = 30


def current_session(user):
    from apps.analytics.models import UserSession
    return UserSession.objects.filter(user=user, ended_at__isnull=True).order_by('-last_seen_at').first()


def set_break(user, on, now=None):
    """Start or end a break on their open session. Returns the session, or None."""
    now = now or timezone.now()
    session = current_session(user)
    if session is None:
        return None
    if on and session.on_break_since is None:
        session.on_break_since = now
        session.break_alerted_at = None
    elif not on:
        session.on_break_since = None
        session.break_alerted_at = None
        session.last_seen_at = now
    session.save(update_fields=['on_break_since', 'break_alerted_at', 'last_seen_at'])
    return session


def alert_long_breaks(now=None):
    """Tell each branch's Branch Manager about breaks past the limit. Returns how many."""
    from apps.accounts.models import CustomUser
    from apps.analytics.models import UserSession
    from apps.notifications.services import notify

    now = now or timezone.now()
    long = (UserSession.objects
            .filter(ended_at__isnull=True, break_alerted_at__isnull=True,
                    on_break_since__lte=now - timedelta(minutes=BREAK_ALERT_MINUTES))
            .select_related('user'))
    told = 0
    for session in long:
        person = session.user
        minutes = int((now - session.on_break_since).total_seconds() // 60)
        managers = CustomUser.objects.filter(branch_id=person.branch_id, is_active=True,
                                             role__name='BRANCH_MANAGER').exclude(pk=person.pk)
        for manager in managers:
            notify(recipient=manager, verb='system', actor=person, link='/bm/staff/',
                   message=f'{person.full_name} has been on break for {minutes} minutes.')
        UserSession.objects.filter(pk=session.pk).update(break_alerted_at=now)
        told += 1
    return told
