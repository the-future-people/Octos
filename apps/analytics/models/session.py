from django.db import models


class UserSession(models.Model):
    """
    Tracks a single portal session for a user.
    Created on portal load (via JS heartbeat on first API call).
    Closed on logout, browser close, or session timeout.

    Idle periods and critical-action visibility events are counted
    here as aggregates — the raw events live in AuditEvent.

    Design rules:
    - One open session per user at a time (ended_at=None)
    - last_seen_at updated by frontend heartbeat every 60s
    - Session considered timed out if last_seen_at > 15min ago
    - active_duration = total_duration - idle_duration
    """

    PORTAL_ATTENDANT        = 'ATTENDANT'
    PORTAL_CASHIER          = 'CASHIER'
    PORTAL_BRANCH_MANAGER   = 'BRANCH_MANAGER'
    PORTAL_REGIONAL_MANAGER = 'REGIONAL_MANAGER'
    PORTAL_FINANCE          = 'FINANCE'
    PORTAL_BELT_MANAGER     = 'BELT_MANAGER'

    PORTAL_CHOICES = [
        (PORTAL_ATTENDANT,        'Attendant Portal'),
        (PORTAL_CASHIER,          'Cashier Portal'),
        (PORTAL_BRANCH_MANAGER,   'Branch Manager Portal'),
        (PORTAL_REGIONAL_MANAGER, 'Regional Manager Portal'),
        (PORTAL_FINANCE,          'Finance Portal'),
        (PORTAL_BELT_MANAGER,     'Belt Manager Portal'),
    ]

    # ── Identity ──────────────────────────────────────────────
    user   = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.CASCADE,
        related_name = 'portal_sessions',
    )
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete    = models.SET_NULL,
        null         = True,
        blank        = True,
        related_name = 'portal_sessions',
        help_text    = 'Null for HQ-level users (Finance, Belt Manager)',
    )
    portal = models.CharField(
        max_length = 20,
        choices    = PORTAL_CHOICES,
        db_index   = True,
    )

    # ── Timing ────────────────────────────────────────────────
    started_at   = models.DateTimeField(db_index=True)
    ended_at     = models.DateTimeField(
        null      = True,
        blank     = True,
        help_text = 'Null means session is still active',
    )
    last_seen_at = models.DateTimeField(
        help_text = 'Updated by frontend heartbeat every 60s',
    )

    # ── Duration breakdown (seconds) ──────────────────────────
    total_duration_seconds  = models.PositiveIntegerField(default=0)
    active_duration_seconds = models.PositiveIntegerField(default=0)
    idle_duration_seconds   = models.PositiveIntegerField(default=0)

    # ── Anomaly signals ───────────────────────────────────────
    idle_count = models.PositiveSmallIntegerField(
        default   = 0,
        help_text = 'Number of idle periods > IDLE_THRESHOLD (default 5 min)',
    )
    critical_action_switches = models.PositiveSmallIntegerField(
        default   = 0,
        help_text = (
            'Tab/app switches detected during critical actions '
            '(payment confirmation, EOD sign-off). '
            'These are the high-signal events — not all tab switches.'
        ),
    )

    # ── Network context ───────────────────────────────────────
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    # ── Risk assessment ───────────────────────────────────────
    is_anomalous  = models.BooleanField(
        default   = False,
        db_index  = True,
        help_text = 'Set by daily_risk_engine if session pattern is unusual',
    )
    anomaly_notes = models.TextField(
        blank     = True,
        help_text = 'Human-readable explanation of what triggered is_anomalous',
    )

    class Meta:
        ordering = ['-started_at']
        indexes  = [
            models.Index(fields=['user', 'started_at']),
            models.Index(fields=['branch', 'started_at']),
            models.Index(fields=['portal', 'started_at']),
            models.Index(fields=['is_anomalous', 'started_at']),
        ]
        verbose_name        = 'User Session'
        verbose_name_plural = 'User Sessions'

    def __str__(self):
        status = 'active' if not self.ended_at else 'closed'
        return (
            f"{self.user.full_name} — {self.portal} "
            f"[{self.started_at.strftime('%Y-%m-%d %H:%M')}] ({status})"
        )

    @property
    def is_active(self):
        return self.ended_at is None

    @property
    def duration_minutes(self):
        if not self.total_duration_seconds:
            return 0
        return round(self.total_duration_seconds / 60, 1)

    @property
    def active_minutes(self):
        if not self.active_duration_seconds:
            return 0
        return round(self.active_duration_seconds / 60, 1)