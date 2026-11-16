from django.db import models

from apps.core.models import AuditModel


class ProfileChange(AuditModel):
    """
    A change a staff member asked for on their own profile (16 Nov 2026):
    a new phone, email or photo. It waits for the Branch Manager and only
    takes effect when he approves it.

    One open request per person per field: asking again replaces the one
    still waiting. The Branch Manager's own changes, and changes he makes
    for his staff, apply at once and never come through here.
    """

    class Field(models.TextChoices):
        PHONE = 'PHONE', 'Phone'
        EMAIL = 'EMAIL', 'Email'
        PHOTO = 'PHOTO', 'Photo'

    class Status(models.TextChoices):
        PENDING  = 'PENDING',  'Waiting for the Branch Manager'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Not approved'
        REPLACED = 'REPLACED', 'Replaced by a newer request'

    user = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='profile_changes')
    field = models.CharField(max_length=10, choices=Field.choices)
    new_value = models.CharField(max_length=254, blank=True, help_text='The phone or email asked for.')
    new_photo = models.ImageField(upload_to='employees/pending/', null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    decided_by = models.ForeignKey('accounts.CustomUser', null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='profile_changes_decided')
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True, help_text="The Branch Manager's reason, when he says no.")

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'field'], condition=models.Q(status='PENDING'),
                                    name='one_pending_change_per_field'),
        ]

    def __str__(self):
        return f'{self.user} asks to change {self.get_field_display().lower()} ({self.status})'
