"""
The Can-Do Sandbox (23 Nov 2026).

A customer shows Octos a photo, short video or GIF of something like what
they want ("can you do this?"), on WhatsApp or on the website. Octos first
works out what it is, using the web where it needs to, and only then turns
to Farhat: can we make it, how, roughly what it costs and when it'd be ready.

Every look is kept as a case, with what happened after (a job made, the
boss's own answer when Octos wasn't sure), so the next similar question is
answered the way Farhat actually answered it.
"""
import secrets

from django.db import models


def new_code():
    """SB-7K3QXA: short, easy to read out, and not guessable."""
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return 'SB-' + ''.join(secrets.choice(alphabet) for _ in range(6))


class SandboxCase(models.Model):
    WEB, WHATSAPP, STAFF = 'WEB', 'WHATSAPP', 'STAFF'
    SOURCES = [(WEB, 'Website'), (WHATSAPP, 'WhatsApp'), (STAFF, 'Staff')]

    QUEUED, RUNNING, DONE, UNSURE, FAILED = 'QUEUED', 'RUNNING', 'DONE', 'UNSURE', 'FAILED'
    STATUSES = [(QUEUED, 'Waiting'), (RUNNING, 'Looking'), (DONE, 'Answered'),
                (UNSURE, 'Not sure: asked the team'), (FAILED, 'Failed')]

    # The four steps the customer watches tick off.
    STEPS = ['Looking at your photo', 'Searching to identify it', 'Checking what we can make',
             'Working out price and time']

    code = models.CharField(max_length=12, unique=True, default=new_code)
    source = models.CharField(max_length=10, choices=SOURCES)
    status = models.CharField(max_length=10, choices=STATUSES, default=QUEUED)
    stage = models.PositiveSmallIntegerField(default=0)       # steps done, 0 to 4
    findings = models.JSONField(default=list, blank=True)     # one short line per step done
    note = models.CharField(max_length=500, blank=True)       # what the customer added
    files = models.JSONField(default=list, blank=True)        # stored paths of what they showed us
    result = models.JSONField(default=dict, blank=True)       # the answer card
    error = models.TextField(blank=True)

    conversation = models.ForeignKey('communications.Conversation', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='sandbox_cases')
    visitor = models.CharField(max_length=64, blank=True)     # a hash of the website visitor, for the daily limit

    # What happened after: how Octos learns Farhat's answers.
    job = models.ForeignKey('jobs.Job', null=True, blank=True, on_delete=models.SET_NULL,
                            related_name='sandbox_cases')
    owner_answer = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['visitor', 'created_at'])]

    def __str__(self):
        return f"{self.code} · {self.result.get('what') or self.get_status_display()}"
