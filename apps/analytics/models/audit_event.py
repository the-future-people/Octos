from django.db import models


class AuditEvent(models.Model):
    """
    Immutable record of a significant operational event.

    Written by Django signal handlers in analytics/signals/handlers.py.
    Never written directly by views or engines.
    Never updated after creation — the save() method enforces this.

    Every field is populated at write time. The metadata JSONField
    captures the full context of the event so it can be understood
    in isolation, years later, without querying related models.

    Design rules:
    - Immutable: raises ValueError on update attempt
    - Explicit timestamp: not auto_now_add (supports backfill)
    - metadata must be self-contained: include names, amounts,
      references — don't rely on FK lookups to understand an event
    """

    # ── Event type constants ──────────────────────────────────

    # Session events
    SESSION_START          = 'SESSION_START'
    SESSION_END            = 'SESSION_END'
    SESSION_IDLE           = 'SESSION_IDLE'
    SESSION_TIMEOUT        = 'SESSION_TIMEOUT'
    TAB_SWITCH_CRITICAL    = 'TAB_SWITCH_CRITICAL'

    # Sheet events
    SHEET_OPENED           = 'SHEET_OPENED'
    SHEET_CLOSED           = 'SHEET_CLOSED'
    SHEET_AUTO_CLOSED      = 'SHEET_AUTO_CLOSED'

    # Float events
    FLOAT_SET              = 'FLOAT_SET'
    FLOAT_ACKNOWLEDGED     = 'FLOAT_ACKNOWLEDGED'
    FLOAT_SIGNED_OFF       = 'FLOAT_SIGNED_OFF'
    FLOAT_VARIANCE         = 'FLOAT_VARIANCE'

    # Job events
    JOB_CREATED            = 'JOB_CREATED'
    JOB_MODIFIED           = 'JOB_MODIFIED'
    JOB_VOIDED             = 'JOB_VOIDED'
    JOB_STATUS_CHANGED     = 'JOB_STATUS_CHANGED'
    JOB_POST_CLOSING       = 'JOB_POST_CLOSING'

    # Payment events
    PAYMENT_CONFIRMED      = 'PAYMENT_CONFIRMED'
    PAYMENT_LATE           = 'PAYMENT_LATE'
    PAYMENT_OUTSIDE_SHIFT  = 'PAYMENT_OUTSIDE_SHIFT'

    # Petty cash
    PETTY_CASH_RECORDED    = 'PETTY_CASH_RECORDED'

    # Credit events
    CREDIT_ISSUED          = 'CREDIT_ISSUED'
    CREDIT_SETTLED         = 'CREDIT_SETTLED'

    # Auth events
    LOGIN_SUCCESS          = 'LOGIN_SUCCESS'
    LOGIN_FAILED           = 'LOGIN_FAILED'
    LOGOUT                 = 'LOGOUT'
    PIN_USED               = 'PIN_USED'

    # Monthly close events
    MONTHLY_SUBMITTED      = 'MONTHLY_SUBMITTED'
    MONTHLY_FINANCE_REVIEW = 'MONTHLY_FINANCE_REVIEW'
    MONTHLY_CLARIFICATION  = 'MONTHLY_CLARIFICATION'
    MONTHLY_RESUBMITTED    = 'MONTHLY_RESUBMITTED'
    MONTHLY_ENDORSED       = 'MONTHLY_ENDORSED'
    MONTHLY_REJECTED       = 'MONTHLY_REJECTED'
    MONTHLY_LOCKED         = 'MONTHLY_LOCKED'

    EVENT_TYPE_CHOICES = [
        # Session
        (SESSION_START,          'Session Started'),
        (SESSION_END,            'Session Ended'),
        (SESSION_IDLE,           'Session Idle'),
        (SESSION_TIMEOUT,        'Session Timed Out'),
        (TAB_SWITCH_CRITICAL,    'Tab Switch During Critical Action'),
        # Sheet
        (SHEET_OPENED,           'Sheet Opened'),
        (SHEET_CLOSED,           'Sheet Closed'),
        (SHEET_AUTO_CLOSED,      'Sheet Auto-Closed'),
        # Float
        (FLOAT_SET,              'Float Set'),
        (FLOAT_ACKNOWLEDGED,     'Float Acknowledged'),
        (FLOAT_SIGNED_OFF,       'Float Signed Off'),
        (FLOAT_VARIANCE,         'Float Variance Detected'),
        # Jobs
        (JOB_CREATED,            'Job Created'),
        (JOB_MODIFIED,           'Job Modified'),
        (JOB_VOIDED,             'Job Voided'),
        (JOB_STATUS_CHANGED,     'Job Status Changed'),
        (JOB_POST_CLOSING,       'Post-Closing Job Created'),
        # Payments
        (PAYMENT_CONFIRMED,      'Payment Confirmed'),
        (PAYMENT_LATE,           'Late Payment'),
        (PAYMENT_OUTSIDE_SHIFT,  'Payment Outside Shift Hours'),
        # Petty cash
        (PETTY_CASH_RECORDED,    'Petty Cash Recorded'),
        # Credit
        (CREDIT_ISSUED,          'Credit Issued'),
        (CREDIT_SETTLED,         'Credit Settled'),
        # Auth
        (LOGIN_SUCCESS,          'Login Successful'),
        (LOGIN_FAILED,           'Login Failed'),
        (LOGOUT,                 'Logout'),
        (PIN_USED,               'PIN Used'),
        # Monthly close
        (MONTHLY_SUBMITTED,      'Monthly Close Submitted'),
        (MONTHLY_FINANCE_REVIEW, 'Monthly Close Finance Review'),
        (MONTHLY_CLARIFICATION,  'Monthly Close Clarification Requested'),
        (MONTHLY_RESUBMITTED,    'Monthly Close Resubmitted'),
        (MONTHLY_ENDORSED,       'Monthly Close Endorsed'),
        (MONTHLY_REJECTED,       'Monthly Close Rejected'),
        (MONTHLY_LOCKED,         'Monthly Close Locked'),
    ]

    # ── Severity constants ────────────────────────────────────
    INFO     = 'INFO'
    LOW      = 'LOW'
    MEDIUM   = 'MEDIUM'
    HIGH     = 'HIGH'
    CRITICAL = 'CRITICAL'

    SEVERITY_CHOICES = [
        (INFO,     'Info'),
        (LOW,      'Low'),
        (MEDIUM,   'Medium'),
        (HIGH,     'High'),
        (CRITICAL, 'Critical'),
    ]

    # ── Core identity ─────────────────────────────────────────
    user = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.SET_NULL,
        null         = True,
        blank        = True,
        related_name = 'audit_events',
        help_text    = 'Null for system-generated events',
    )
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete    = models.SET_NULL,
        null         = True,
        blank        = True,
        related_name = 'audit_events',
    )
    session = models.ForeignKey(
        'analytics.UserSession',
        on_delete    = models.SET_NULL,
        null         = True,
        blank        = True,
        related_name = 'events',
        help_text    = 'The portal session during which this event occurred',
    )

    # ── Event classification ──────────────────────────────────
    event_type = models.CharField(
        max_length = 30,
        choices    = EVENT_TYPE_CHOICES,
        db_index   = True,
    )
    severity = models.CharField(
        max_length = 10,
        choices    = SEVERITY_CHOICES,
        default    = INFO,
        db_index   = True,
    )

    # ── Affected entity ───────────────────────────────────────
    entity_type = models.CharField(
        max_length = 50,
        blank      = True,
        help_text  = "Model class name e.g. 'Job', 'CashierFloat', 'Receipt'",
    )
    entity_id = models.PositiveIntegerField(
        null      = True,
        blank     = True,
        help_text = 'PK of the affected record',
    )

    # ── Rich context ──────────────────────────────────────────
    metadata = models.JSONField(
        default   = dict,
        help_text = (
            'Self-contained context captured at event time. '
            'Must be understandable without querying related models. '
            'Example for PAYMENT_CONFIRMED: '
            '{"amount": 150.00, "method": "CASH", '
            '"job_number": "WLB-0042", "tendered": 200.00, '
            '"change": 50.00, "queue_wait_minutes": 3}'
        ),
    )

    # ── Timing ────────────────────────────────────────────────
    timestamp = models.DateTimeField(
        db_index  = True,
        help_text = (
            'Explicit timestamp — not auto_now_add. '
            'Allows backfill of historical events.'
        ),
    )

    # ── Risk signal ───────────────────────────────────────────
    risk_score = models.PositiveSmallIntegerField(
        default   = 0,
        help_text = (
            '0–100. Assigned by daily_risk_engine during EOD analysis. '
            '0 at creation time for most events.'
        ),
    )

    class Meta:
        ordering = ['-timestamp']
        indexes  = [
            models.Index(fields=['branch', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['event_type', 'timestamp']),
            models.Index(fields=['severity', 'timestamp']),
            models.Index(fields=['entity_type', 'entity_id']),
        ]
        verbose_name        = 'Audit Event'
        verbose_name_plural = 'Audit Events'

    def __str__(self):
        user_str = self.user.full_name if self.user else 'System'
        return f"[{self.severity}] {self.event_type} — {user_str} @ {self.timestamp}"

    def save(self, *args, **kwargs):
        """AuditEvent is immutable. Raises on any update attempt."""
        if self.pk:
            raise ValueError(
                'AuditEvent is immutable — records cannot be updated. '
                'Create a new event instead.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """AuditEvent cannot be deleted."""
        raise ValueError(
            'AuditEvent records cannot be deleted. '
            'They are permanent audit records.'
        )