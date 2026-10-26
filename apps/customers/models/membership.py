"""
A person's link to a business or institution.

A business and a person are separate customers: Piwak Construction Ltd
pays for Piwak's jobs, Edward Appiah for his own. This is what connects
them: Edward is Piwak's rep. One person can be linked to several (a
union's rep who is also a church's secretary), each link with its role,
whether the business has named them as one of the people who may order
for it, and when it started and ended.

Anyone may order in a business's name if they say so at the counter;
linked people are suggested first. "Named" only lets a business say who
it expects, and the counter warns, never blocks.

When someone leaves, the link is ended, not deleted: every job they
ordered keeps its history exactly as it was.
"""

from django.db import models
from django.utils import timezone


class Membership(models.Model):

    class Role(models.TextChoices):
        REP = 'REP', 'Representative'
        STAFF = 'STAFF', 'Staff'
        OWNER = 'OWNER', 'Owner'
        MEMBER = 'MEMBER', 'Member'

    person = models.ForeignKey('customers.CustomerProfile', on_delete=models.CASCADE,
                               related_name='memberships')
    organisation = models.ForeignKey('customers.CustomerProfile', on_delete=models.CASCADE,
                                     related_name='members')
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    # The business has named this person as one who may order for it.
    named = models.BooleanField(default=False)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-started_at']
        constraints = [
            models.UniqueConstraint(
                fields=['person', 'organisation'], condition=models.Q(ended_at__isnull=True),
                name='one_open_link_per_person_and_organisation',
            ),
        ]

    @property
    def active(self):
        return self.ended_at is None

    def end(self):
        """They have left: the link ends, the history stays."""
        if self.ended_at is None:
            self.ended_at = timezone.now()
            self.save(update_fields=['ended_at'])

    def __str__(self):
        return f'{self.person_id} {self.get_role_display()} of {self.organisation_id}'