"""
What the Print Octos app is told, and where to tell it.

DeviceToken is a phone's address for push notifications, tied to the
signed-in session that registered it: signing out of that phone stops
its notifications, and a phone that has gone away is forgotten the
first time a push to it is refused.

AppNotification is the inbox: every message stored, read or unread,
with whether it went out by push, by SMS, or both. It is what the bell
shows, and what proves a customer was told.
"""

from django.db import models

from apps.core.models import AuditModel


class DeviceToken(AuditModel):
    session = models.ForeignKey(
        'storefront.AppSession', on_delete=models.CASCADE, related_name='devices',
    )
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=10, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.platform or "phone"} for {self.session.lead.phone}'


class AppNotification(AuditModel):
    lead = models.ForeignKey(
        'storefront.Lead', on_delete=models.CASCADE, related_name='notifications',
    )
    order = models.ForeignKey(
        'storefront.OnlineOrder', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='notifications',
    )
    kind = models.CharField(max_length=30)
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=300)
    pushed = models.BooleanField(default=False)
    texted = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.kind} for {self.lead.phone}'