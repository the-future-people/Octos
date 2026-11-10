"""
Event: one fact that happened in Octos. Append-only.

Why append-only: an event is history. "Kingsford took over conversation 351
at 10:12" stays true forever, even after he hands it back. So an event is
never edited and never deleted; a later event records the change instead.
The database row says what IS; the event log says what HAPPENED.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Event(models.Model):
    # Who caused it
    CUSTOMER, STAFF, OCTOS, SYSTEM, PROVIDER = 'customer', 'staff', 'octos', 'system', 'provider'
    ACTOR_CHOICES = [
        (CUSTOMER, 'Customer'),
        (STAFF, 'Staff'),
        (OCTOS, 'Octos'),           # Octos's own decisions
        (SYSTEM, 'System'),         # scheduled tasks, timers
        (PROVIDER, 'Provider'),     # Meta, Paystack, mNotify telling us something
    ]

    kind = models.CharField(max_length=64, db_index=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True,
                                       help_text='When it happened in the world.')
    recorded_at = models.DateTimeField(auto_now_add=True,
                                       help_text='When Octos wrote it down.')

    actor = models.CharField(max_length=10, choices=ACTOR_CHOICES, default=SYSTEM)
    actor_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')

    # What it is about. Each may be empty; most events fill one or two.
    customer = models.ForeignKey('customers.CustomerProfile', null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name='events')
    conversation = models.ForeignKey('communications.Conversation', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='events')
    job = models.ForeignKey('jobs.Job', null=True, blank=True,
                            on_delete=models.SET_NULL, related_name='events')
    branch = models.ForeignKey('organization.Branch', null=True, blank=True,
                               on_delete=models.SET_NULL, related_name='events')

    payload = models.JSONField(default=dict, blank=True,
                               help_text='The details: ids, amounts, file sizes, scores.')
    reason = models.TextField(blank=True,
                              help_text='Why it happened, in words a person can read.')

    # Idempotency: the same real-world fact (one WhatsApp message, one Paystack
    # payment) must be recorded once even if its webhook arrives twice.
    # Unique where set; many events have no natural key and leave it empty.
    idempotency_key = models.CharField(max_length=160, null=True, blank=True, unique=True)

    class Meta:
        ordering = ['occurred_at', 'id']
        indexes = [
            models.Index(fields=['conversation', 'occurred_at']),
            models.Index(fields=['customer', 'occurred_at']),
            models.Index(fields=['kind', 'occurred_at']),
        ]

    def __str__(self):
        return f'{self.occurred_at:%d %b %H:%M} {self.kind}'

    # Append-only, enforced in code: refuse edits and deletes.
    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('Events are append-only: record a new event instead of editing one.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Events are append-only and cannot be deleted.')
