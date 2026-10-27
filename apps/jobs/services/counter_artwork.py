"""
Artwork uploaded at the counter, attached to the job and its line.

The counter checks a file exactly as the app does (the same check, the
same signed verdict), so a counter job reaches the coordinator and the
operator in the same shape as an online one: its file, the verdict the
customer was told, and which line it belongs to.

    read(token, service, specs)   the staged upload behind a verdict, or a refusal
    attach(job, staged, user)     each line's file onto the job, after it is made
"""

from rest_framework import serializers


def read(token, service, specifications):
    """
    The staged upload this verdict was given for, or a ValidationError.
    The same check the app's commit makes: the file that passed is the
    file that is attached.
    """
    from apps.storefront.views import _staged_for
    staged, refusal = _staged_for(token, service, specifications or {})
    if refusal:
        raise serializers.ValidationError(refusal)
    return staged


def attach(job, staged_per_line, user):
    """
    Each line's file onto the job, linked to its line, with its verdict.
    The lines are matched in the order they were sent, which is the order
    they were made.
    """
    from apps.jobs.models import JobFile, JobLineItem

    if not any(staged_per_line):
        return
    lines = list(JobLineItem.objects.filter(job=job, parent__isnull=True).order_by('id'))
    for line, staged in zip(lines, staged_per_line):
        if staged is None:
            continue
        record = JobFile(
            job=job,
            line_item=line,
            uploaded_by=user,
            original_filename=staged.original_filename,
            size_bytes=staged.size_bytes,
            content_type=staged.content_type,
            verdict=staged.verdict,
            checks=staged.checks,
            **staged.measured(),
        )
        staged.file.open('rb')
        record.file.save(staged.original_filename, staged.file, save=False)
        record.save()
        staged.file.close()
        staged.file.delete(save=False)
        staged.delete()