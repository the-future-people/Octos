"""
How many people a branch has working a station.

A machine's speed is not a branch's speed. Two people at the printer
means two banners print at once and the queue clears twice as fast; one
person at finishing means everything funnels through them however fast
the printing was.

So capacity is people, not machines, and it differs by branch: Westland
may have two at finishing where a smaller branch has one.

Kept as a number per branch per station rather than derived from who is
clocked in. Deriving it would be truer, but it needs every member of
staff tagged with the stations they work and the floor keeping that
current — a habit nobody has yet. A number someone sets when they train
a second operator is honest and is exercised from the first day.

A station with no row here is one person. That is the common case and
should not need a row to say so.
"""

from django.db import models

from apps.core.models import AuditModel


class BranchStation(AuditModel):
    branch = models.ForeignKey(
        'organization.Branch',
        on_delete=models.CASCADE,
        related_name='station_capacity',
    )
    station = models.ForeignKey(
        'production.Station',
        on_delete=models.CASCADE,
        related_name='branch_capacity',
    )

    people = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            'How many jobs this branch can work at this station at once. '
            'Usually the number of trained people, not machines — a second '
            'printer with nobody to run it adds no capacity.'
        ),
    )

    notes = models.TextField(
        blank=True,
        help_text='Why it is this number, so the next person to change it knows.',
    )

    class Meta:
        ordering = ['branch__code', 'station__sequence']
        constraints = [
            models.UniqueConstraint(
                fields=['branch', 'station'],
                name='one_capacity_row_per_branch_station',
            ),
        ]

    def __str__(self):
        return f'{self.branch.code} {self.station.code}: {self.people}'

    @classmethod
    def people_at(cls, branch, station):
        """
        How many at this station, defaulting to one.

        A missing row means one person rather than none — the common
        case should not need a row to say so, and returning zero here
        would make the engine divide by it.
        """
        row = cls.objects.filter(branch=branch, station=station).first()
        return max(1, row.people if row else 1)