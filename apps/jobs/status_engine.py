from django.utils import timezone
from django.db import transaction


# Valid transitions per job type
# Format: { current_status: [allowed_next_statuses] }

INSTANT_TRANSITIONS = {
    'DRAFT': ['CONFIRMED', 'CANCELLED'],
    'CONFIRMED': ['READY_FOR_PAYMENT', 'CANCELLED'],
    'READY_FOR_PAYMENT': ['PAID', 'CANCELLED'],
    'PAID': ['COMPLETE'],
    'COMPLETE': [],
    'CANCELLED': [],
}

PRODUCTION_TRANSITIONS = {
    'DRAFT': ['CONFIRMED', 'CANCELLED'],
    'CONFIRMED': ['QUEUED', 'CANCELLED'],
    'QUEUED': ['IN_PROGRESS', 'CANCELLED'],
    'IN_PROGRESS': ['READY_FOR_PAYMENT', 'CANCELLED'],
    'READY_FOR_PAYMENT': ['PAID', 'CANCELLED'],
    'PAID': ['OUT_FOR_DELIVERY', 'COMPLETE'],
    'OUT_FOR_DELIVERY': ['COMPLETE'],
    'COMPLETE': [],
    'CANCELLED': [],
}

DESIGN_TRANSITIONS = {
    'DRAFT': ['CONFIRMED', 'CANCELLED'],
    'CONFIRMED': ['BRIEFED', 'CANCELLED'],
    'BRIEFED': ['DESIGN_IN_PROGRESS', 'CANCELLED'],
    'DESIGN_IN_PROGRESS': ['SAMPLE_SENT', 'CANCELLED'],
    'SAMPLE_SENT': ['REVISION_REQUESTED', 'DESIGN_APPROVED', 'CANCELLED'],
    'REVISION_REQUESTED': ['DESIGN_IN_PROGRESS', 'CANCELLED'],
    'DESIGN_APPROVED': ['QUEUED', 'CANCELLED'],
    'QUEUED': ['IN_PROGRESS', 'CANCELLED'],
    'IN_PROGRESS': ['READY_FOR_PAYMENT', 'CANCELLED'],
    'READY_FOR_PAYMENT': ['PAID', 'CANCELLED'],
    'PAID': ['OUT_FOR_DELIVERY', 'COMPLETE'],
    'OUT_FOR_DELIVERY': ['COMPLETE'],
    'COMPLETE': [],
    'CANCELLED': [],
}

TRANSITION_MAP = {
    'INSTANT': INSTANT_TRANSITIONS,
    'PRODUCTION': PRODUCTION_TRANSITIONS,
    'DESIGN': DESIGN_TRANSITIONS,
}


class JobStatusEngine:
    """
    Controls all job status transitions.
    - Enforces valid transitions per job type
    - Logs every transition with actor and timestamp
    - Raises clear errors on illegal transitions
    No job status ever changes outside this engine.
    """

    def __init__(self, job):
        self.job = job
        self.transitions = TRANSITION_MAP.get(job.job_type, {})

    def can_transition(self, to_status):
        allowed = self.transitions.get(self.job.status, [])
        return to_status in allowed

    def get_allowed_transitions(self):
        return self.transitions.get(self.job.status, [])

    @transaction.atomic
    def transition(self, to_status, actor, notes=''):
        """
        Execute a status transition.

        Args:
            to_status: The target status string
            actor: CustomUser performing the transition
            notes: Optional notes about the transition

        Returns:
            dict with success, from_status, to_status, timestamp

        Raises:
            ValueError: If transition is not allowed
        """
        from apps.jobs.models.job_status_log import JobStatusLog

        if not self.can_transition(to_status):
            allowed = self.get_allowed_transitions()
            raise ValueError(
                f"Cannot transition job {self.job.job_number} "
                f"from '{self.job.status}' to '{to_status}'. "
                f"Allowed transitions: {allowed}"
            )

        from_status = self.job.status
        now = timezone.now()

        self.job.status = to_status
        self.job.save(update_fields=['status', 'updated_at'])

        JobStatusLog.objects.create(
            job=self.job,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            notes=notes,
            transitioned_at=now
        )

        return {
            'success': True,
            'job_number': self.job.job_number,
            'from_status': from_status,
            'to_status': to_status,
            'actor': actor.get_full_name() or actor.email,
            'timestamp': now.isoformat(),
        }

    @classmethod
    def advance(cls, job, to_status, actor, notes=''):
        engine = cls(job)
        return engine.transition(to_status, actor, notes)