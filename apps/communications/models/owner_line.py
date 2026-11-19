from django.db import models


class OwnerMessage(models.Model):
    """
    The owner's private WhatsApp line (18 Nov 2026): every message between
    Octos and the owner's own number, both ways.

    Kept apart from Conversation and Message on purpose. The reports carry
    the business's money, so nothing here may reach the inbox, the customer
    assistant, staff alerts or the analytics that read conversations.

    WAITING is a message ready for the owner while WhatsApp's 24-hour window
    is shut: a short approved template knocks, and the owner's tap (any
    message from them) opens the window and sends everything waiting.
    """
    IN, OUT = 'IN', 'OUT'
    DIRECTIONS = [(IN, 'From the owner'), (OUT, 'To the owner')]

    # What an outgoing message is.
    BRIEF, CLOSE, URGENT, ANSWER, KNOCK = 'BRIEF', 'CLOSE', 'URGENT', 'ANSWER', 'KNOCK'
    KINDS = [(BRIEF, 'Morning brief'), (CLOSE, 'Day close'), (URGENT, 'Urgent'),
             (ANSWER, 'Answer'), (KNOCK, 'Knock (template)')]

    WAITING, QUEUED, SENT, FAILED, SKIPPED, RECEIVED = 'WAITING', 'QUEUED', 'SENT', 'FAILED', 'SKIPPED', 'RECEIVED'
    STATUSES = [(WAITING, 'Waiting for the window'), (QUEUED, 'Queued'), (SENT, 'Sent'),
                (FAILED, 'Failed'), (SKIPPED, 'No longer needed'), (RECEIVED, 'Received')]

    direction = models.CharField(max_length=3, choices=DIRECTIONS)
    kind      = models.CharField(max_length=10, choices=KINDS, blank=True)
    status    = models.CharField(max_length=10, choices=STATUSES)
    body      = models.TextField(blank=True)
    # Up to three reply buttons: [{"id": "cut:approve:12", "title": "Approve"}].
    buttons   = models.JSONField(default=list, blank=True)
    # The picture card, when there is one (a report). Small PNGs, few rows.
    card      = models.BinaryField(null=True, blank=True)
    # One send per event: 'cut:12', 'machine-down:3:2026-11-18T09:12', 'brief:2026-11-18'.
    key       = models.CharField(max_length=120, null=True, blank=True, unique=True)
    # What it is about, to tell at sending time whether it still matters ('cut:12').
    ref       = models.CharField(max_length=60, blank=True)
    # The button the owner tapped, on an incoming message.
    reply_id  = models.CharField(max_length=120, blank=True)
    external_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    error     = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at   = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.direction} {self.kind or "message"} {self.status} {self.created_at:%d %b %H:%M}'


class OwnerWatch(models.Model):
    """
    A customer chat the owner asked Octos to keep an eye on (19 Nov 2026):
    "respond to the message and see what he wants, report back". When the
    customer writes again, Octos reports to the owner's line what they said
    and how it was answered.

    NEXT ends after the first report; KEEP reports every reply until the
    watch runs out (ends_at) or the owner stops it.
    """
    NEXT, KEEP = 'NEXT', 'KEEP'
    MODES = [(NEXT, 'Their next reply'), (KEEP, 'Every reply')]

    conversation = models.ForeignKey('communications.Conversation', on_delete=models.CASCADE,
                                     related_name='owner_watches')
    mode       = models.CharField(max_length=4, choices=MODES, default=NEXT)
    started_at = models.DateTimeField(auto_now_add=True)
    ends_at    = models.DateTimeField()
    # The last message already reported: the next report starts after it.
    reported_up_to = models.ForeignKey('communications.Message', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+')
    reports    = models.PositiveSmallIntegerField(default=0)
    done_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [models.Index(fields=['conversation', 'done_at'])]

    def __str__(self):
        return f'Watch on {self.conversation_id} ({self.get_mode_display()})'
