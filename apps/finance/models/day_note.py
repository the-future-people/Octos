from django.db import models
from apps.core.models import AuditModel


class DaySheetNote(AuditModel):
    """
    Something a person wanted said about a particular day.

    Usually a branch manager reviewing the month before filing: a day the
    checks flagged, explained once so it stops being a question. The same
    record carries what Finance asks about that day and what the manager
    answers, because they are the same conversation — an explanation
    written before it is asked for and one written after should not live
    in two different places.

    Notes are never edited or removed. A day that looked odd, was
    explained, and then queried anyway should read in that order.
    """

    class Kind(models.TextChoices):
        REVIEW   = 'REVIEW',   'Reviewed by the manager'
        QUERY    = 'QUERY',    'Asked by Finance'
        RESPONSE = 'RESPONSE', 'Answered by the manager'

    # 'day_notes' rather than 'notes': the sheet already has a notes field
    # of its own, and the two are different things — that one is what was
    # written on the day, these are what was said about it afterwards.
    daily_sheet = models.ForeignKey(
        'finance.DailySalesSheet',
        on_delete    = models.CASCADE,
        related_name = 'day_notes',
    )
    kind = models.CharField(
        max_length = 10,
        choices    = Kind.choices,
        default    = Kind.REVIEW,
    )
    body = models.TextField(
        help_text='Why this day is the way it is, in the writer\'s own words.',
    )
    author = models.ForeignKey(
        'accounts.CustomUser',
        on_delete    = models.PROTECT,
        related_name = 'day_notes',
    )
    # What the checks said at the time of writing. Kept because the
    # thresholds will change: a note explaining a flag reads oddly later
    # if the flag it answered no longer fires.
    flagged_for = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['created_at']
        verbose_name        = 'Day Sheet Note'
        verbose_name_plural = 'Day Sheet Notes'

    def __str__(self):
        return f'{self.daily_sheet.date} — {self.kind} by {self.author_id}'