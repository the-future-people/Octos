"""
One job per attempt at the counter.

New Job sends a key made fresh for each attempt. The first time a key
arrives, the job is made and the key remembered with it; any time after
(a second press, a retry after a dropped connection, an error shown after
the job was already made) the job already made is returned instead of a
second one. The app's checkout has always worked this way; this brings
the counter in line. A fresh key is made only after a job succeeds.
"""

from django.db import models


class JobRequestKey(models.Model):
    key = models.CharField(max_length=64, unique=True)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='request_keys')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.key} -> {self.job_id}'