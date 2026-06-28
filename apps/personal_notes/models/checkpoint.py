from django.db import models


class TaskCheckpoint(models.Model):
    """
    A single staged check-in for a PersonalNote of type TASK.
    Auto-generated when a note is converted to a task with a due_date,
    evenly spaced between creation time and the due date.

    Owner-scoped indirectly via note.owner — every query touching this
    model must go through note__owner=request.user, same rule as
    PersonalNote itself.
    """

    note = models.ForeignKey(
        'personal_notes.PersonalNote',
        on_delete=models.CASCADE,
        related_name='checkpoints',
    )
    scheduled_at    = models.DateTimeField()
    acknowledged    = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    is_final        = models.BooleanField(
        default=False,
        help_text='True for the last checkpoint before the due date',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering            = ['scheduled_at']
        verbose_name        = 'Task Checkpoint'
        verbose_name_plural = 'Task Checkpoints'
        indexes = [
            models.Index(fields=['note', 'scheduled_at']),
        ]

    def __str__(self):
        return f'Checkpoint for note {self.note_id} @ {self.scheduled_at}'