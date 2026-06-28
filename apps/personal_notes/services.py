"""
personal_notes services
========================
Business logic for task checkpoint generation and lifecycle.
Keeps views thin — same CQRS principle used elsewhere in Octos.
"""

from django.utils import timezone


def generate_checkpoints(note):
    """
    Generates evenly-spaced TaskCheckpoint records for a note that has
    just been converted to a TASK with a due_date set.

    Spacing rule:
      - due within 4 hours  -> 1 checkpoint (now)
      - due within 1-3 days -> 2 checkpoints (now, ~75% of the way there)
      - due beyond 3 days   -> 3 checkpoints (now, midpoint, ~85% of the way there)

    Deletes any existing checkpoints for this note first — safe to call
    again if the due_date is changed.
    """
    from apps.personal_notes.models import TaskCheckpoint

    if not note.due_date:
        return

    now = timezone.now()
    total_seconds = (note.due_date - now).total_seconds()

    # Already overdue or essentially due now — single immediate checkpoint
    if total_seconds <= 0:
        TaskCheckpoint.objects.filter(note=note).delete()
        TaskCheckpoint.objects.create(
            note=note, scheduled_at=now, is_final=True,
        )
        return

    hours_remaining = total_seconds / 3600
    checkpoint_times = [now]  # always start with an immediate checkpoint

    if hours_remaining <= 4:
        pass  # just the immediate one
    elif hours_remaining <= 72:  # 1-3 days
        checkpoint_times.append(now + timezone.timedelta(seconds=total_seconds * 0.75))
    else:  # beyond 3 days
        checkpoint_times.append(now + timezone.timedelta(seconds=total_seconds * 0.5))
        checkpoint_times.append(now + timezone.timedelta(seconds=total_seconds * 0.85))

    TaskCheckpoint.objects.filter(note=note).delete()

    checkpoints = [
        TaskCheckpoint(
            note=note,
            scheduled_at=t,
            is_final=(i == len(checkpoint_times) - 1),
        )
        for i, t in enumerate(checkpoint_times)
    ]
    TaskCheckpoint.objects.bulk_create(checkpoints)


def acknowledge_checkpoint(checkpoint):
    """
    Marks a checkpoint as seen/acknowledged. Called when the user taps
    'Still working on it' in the reminder modal.
    """
    from django.utils import timezone

    checkpoint.acknowledged    = True
    checkpoint.acknowledged_at = timezone.now()
    checkpoint.save(update_fields=['acknowledged', 'acknowledged_at'])


def complete_task(note):
    """
    Marks a task note as complete. Called when the user taps
    'Mark complete', either from the reminder modal or the note editor.
    Acknowledges all remaining checkpoints so they stop firing.
    """
    from django.utils import timezone
    from apps.personal_notes.models import TaskCheckpoint

    note.status       = 'COMPLETE'
    note.completed_at = timezone.now()
    note.save(update_fields=['status', 'completed_at'])

    TaskCheckpoint.objects.filter(
        note=note, acknowledged=False,
    ).update(acknowledged=True, acknowledged_at=timezone.now())