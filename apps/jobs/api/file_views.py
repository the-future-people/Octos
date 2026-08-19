"""
Serving job files.

Nothing is served directly from disk. A customer's artwork at a guessable
URL is a real exposure — anyone who works out the pattern can read another
business's designs — so every request passes through a view that checks who
is asking and whether the file belongs to a job at their branch.

That indirection is also what makes the storage backend swappable. Moving
to object storage later changes how the bytes are fetched here and nothing
else: no caller builds a path, and no URL leaks into a template or an
email.
"""

import logging
import mimetypes
import os

from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import JobFile

logger = logging.getLogger(__name__)

# Serving files is one of the easier ways to hand an attacker the contents
# of a server, so the allowed set is explicit rather than a blocklist.
ALLOWED_EXTENSIONS = {
    '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg',
    '.ai', '.eps', '.psd', '.cdr', '.indd',
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.txt', '.csv', '.zip',
}


class JobFileDownloadView(APIView):
    """
    GET /api/v1/jobs/files/<pk>/

    Streams a file to someone entitled to see it. Files belong to jobs, and
    jobs belong to branches, so entitlement follows the branch — a
    coordinator at one branch has no business reading artwork sent to
    another.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        job_file = (
            JobFile.objects
            .select_related('job__branch')
            .filter(pk=pk)
            .first()
        )
        if not job_file:
            raise Http404

        branch = getattr(request.user, 'branch', None)
        # Finance and HQ roles carry no branch and legitimately see
        # everything; everyone else is held to their own.
        if branch and job_file.job.branch_id != branch.id:
            logger.warning(
                'File %s requested by %s from another branch',
                job_file.pk, request.user.pk,
            )
            raise Http404

        try:
            handle = job_file.file.open('rb')
        except FileNotFoundError:
            # The record survives but the bytes do not — which is exactly
            # what an ephemeral filesystem does on every deploy.
            logger.error(
                'File %s is recorded but missing from storage: %s',
                job_file.pk, job_file.file.name,
            )
            return Response(
                {'detail': 'That file is no longer available.'},
                status=status.HTTP_410_GONE,
            )

        name = os.path.basename(job_file.file.name)
        content_type, _ = mimetypes.guess_type(name)

        response = FileResponse(
            handle,
            content_type=content_type or 'application/octet-stream',
        )
        # inline, so a coordinator can look at artwork without downloading
        # it first. The browser decides what it can display.
        response['Content-Disposition'] = f'inline; filename="{name}"'
        response['X-Content-Type-Options'] = 'nosniff'
        return response