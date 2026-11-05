from django.db import models


class AssistantRun(models.Model):
    """
    One time Octos considered a customer's message: what it looked up,
    what it decided, what it said, and what it cost.

    Every run is kept, including the ones where Octos stayed silent, so
    "why did Octos say that?" and "why didn't Octos answer?" both have an
    answer. The exams read these too.
    """

    REPLIED     = 'REPLIED'
    SHADOWED    = 'SHADOWED'
    HANDED_OVER = 'HANDED_OVER'
    SKIPPED     = 'SKIPPED'
    BLOCKED     = 'BLOCKED'
    FAILED      = 'FAILED'

    DECISION_CHOICES = [
        (REPLIED,     'Replied'),
        (SHADOWED,    'Wrote a shadow note'),
        (HANDED_OVER, 'Handed to a person'),
        (SKIPPED,     'Stayed silent'),
        (BLOCKED,     'Reply blocked by the checker'),
        (FAILED,      'Failed'),
    ]

    conversation = models.ForeignKey(
        'communications.Conversation', on_delete=models.CASCADE, related_name='assistant_runs',
    )
    trigger = models.ForeignKey(
        'communications.Message', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assistant_runs',
        help_text='The customer message Octos was answering.',
    )
    mode     = models.CharField(max_length=10, help_text='shadow or live, at the time.')
    model    = models.CharField(max_length=60, blank=True)
    decision = models.CharField(max_length=12, choices=DECISION_CHOICES)
    reason   = models.CharField(
        max_length=300, blank=True,
        help_text='Why it stayed silent, handed over, or was blocked.',
    )
    reply      = models.TextField(blank=True)
    tool_calls = models.JSONField(
        default=list, blank=True,
        help_text='Each tool Octos called: name, input, and what it got back.',
    )
    sent = models.ForeignKey(
        'communications.Message', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', help_text='The message Octos sent, when it sent one.',
    )
    input_tokens  = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    duration_ms   = models.PositiveIntegerField(default=0)
    error         = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Octos run {self.pk}: {self.decision} on conversation {self.conversation_id}'