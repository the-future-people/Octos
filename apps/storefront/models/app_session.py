"""
A phone signed in to the Print Octos app.

The app holds a long random token and sends it with every request. Only
its hash is kept here, so a copy of the database signs nobody in. A
session lasts while it is used: there is no expiry to surprise someone
mid-order, and it ends when they sign out or delete their account.
"""

from django.db import models

from apps.core.models import AuditModel


class AppSession(AuditModel):
    lead = models.ForeignKey(
        'storefront.Lead',
        on_delete=models.CASCADE,
        related_name='app_sessions',
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    device = models.CharField(max_length=120, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        state = 'revoked' if self.revoked_at else 'active'
        return f'{self.lead.phone} — {state}'

    @property
    def is_active(self):
        return self.revoked_at is None