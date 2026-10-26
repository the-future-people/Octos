"""
The record of one customer merged into another.

A merge is the strongest thing Octos does to a person's records: one of
them stops existing, and everything that pointed at it points at the
other. So every merge keeps a full snapshot of the record that went and
the list of everything that moved, enough to put it back exactly.
"""

from django.db import models


class CustomerMerge(models.Model):
    into = models.ForeignKey('customers.CustomerProfile', on_delete=models.PROTECT, related_name='merges_in')
    merged_pk = models.PositiveIntegerField()
    snapshot = models.JSONField()        # every field of the record that went
    moved = models.JSONField(default=dict)   # {"app.Model.field": [pks]}
    filled = models.JSONField(default=dict)  # survivor fields filled from it
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'#{self.merged_pk} into #{self.into_id}: {self.reason}'