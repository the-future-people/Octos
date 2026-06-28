from django.db import models


class PersonalNote(models.Model):
    """
    A strictly private note belonging to exactly one user.
    No relationship to branches, jobs, customers, or any operational data.

    Visibility rule — enforced at the queryset level everywhere this
    model is touched: owner=request.user, with no exceptions, no
    admin override, no superuser bypass. This is a deliberate design
    constraint, not an oversight.
    """

    COLOR_CHOICES = [
        ('amber',  'Amber'),
        ('blue',   'Blue'),
        ('green',  'Green'),
        ('violet', 'Violet'),
        ('rose',   'Rose'),
        ('slate',  'Slate'),
    ]

    TYPE_CHOICES = [
        ('NOTE', 'Note'),
        ('TASK', 'Task'),
    ]

    STATUS_CHOICES = [
        ('ACTIVE',   'Active'),
        ('COMPLETE', 'Complete'),
    ]

    owner = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='personal_notes',
    )
    title = models.CharField(max_length=120, blank=True)
    body  = models.TextField(blank=True)
    color = models.CharField(max_length=10, choices=COLOR_CHOICES, default='amber')

    note_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='NOTE')
    status    = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ACTIVE')
    due_date  = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    reminder_at         = models.DateTimeField(null=True, blank=True)
    reminder_dismissed  = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering            = ['-updated_at']
        verbose_name        = 'Personal Note'
        verbose_name_plural = 'Personal Notes'

    def __str__(self):
        return f'{self.title or "Untitled"} (owner: {self.owner_id})'