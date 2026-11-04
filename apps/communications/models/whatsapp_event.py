from django.db import models


class WhatsAppEvent(models.Model):
    """
    Every delivery from Meta's webhook, exactly as it arrived.

    Stored before anything reads it. A parser bug then costs nothing but
    a replay: the customer's message is still here, and `error` says what
    went wrong with it.

    Nothing here is unique. Meta gives a delivery no id of its own, and
    one delivery can carry several messages and statuses. Duplicates are
    caught one level down, on each message's wamid.

    processed_at empty and error empty means the parse never finished,
    so a crash mid-way is distinguishable from a clean run.
    """
    payload      = models.JSONField()
    received_at  = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error        = models.TextField(blank=True)

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        if self.error:
            state = 'failed'
        elif self.processed_at:
            state = 'done'
        else:
            state = 'unprocessed'
        return f'WhatsApp event {self.pk} ({state})'