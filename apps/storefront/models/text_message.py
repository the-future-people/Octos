"""
Every text Octos sends, kept.

Until 2 Nov 2026 a text that mNotify accepted but the network refused
looked exactly like one that arrived, and every text failed for weeks
without anyone knowing. Each send is recorded here with what mNotify
said, so failures can be counted, delivery checked later against the
provider's reference, and a message such as the welcome sent only once.
"""

from django.db import models


class TextMessage(models.Model):
    phone = models.CharField(max_length=20, db_index=True,
                             help_text='As sent: international digits, e.g. 233556244194')
    kind = models.CharField(max_length=30, blank=True, db_index=True,
                            help_text='welcome, code, ready, late… Blank for older callers.')
    body = models.TextField()
    sender = models.CharField(max_length=20, blank=True)

    accepted = models.BooleanField(default=False,
                                   help_text="mNotify said success. Not the same as delivered.")
    provider_ref = models.CharField(max_length=64, blank=True, db_index=True,
                                    help_text="mNotify's campaign id, for a delivery check later.")
    provider_code = models.CharField(max_length=20, blank=True)
    provider_message = models.CharField(max_length=200, blank=True)
    credits = models.PositiveSmallIntegerField(default=0)

    # Filled by a delivery check against the provider (to build).
    delivery_status = models.CharField(max_length=20, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['phone', 'kind', 'accepted'], name='text_phone_kind_idx')]

    def __str__(self):
        return f"{self.kind or 'text'} to {self.phone} — {'accepted' if self.accepted else 'not accepted'}"
