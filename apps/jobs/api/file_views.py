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

from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import JobFile

logger = logging.getLogger(__name__)

# A browser fetching an <img> or an <iframe> runs none of the client's
# request interceptors, so the Authorization header never travels and the
# file comes back 401. Every preview in the coordinator's workspace fails
# that way, which defeats the point of inspection.
#
# So a file URL carries a signature, issued by the serializer to someone
# who has already passed the branch check. The signature is the grant: it
# names one file, and it expires.
_signer = TimestampSigner(salt='jobs.file-access')

FILE_LINK_MAX_AGE = 60 * 30


def sign_file_id(pk):
    return _signer.sign(str(pk))


def unsigned_file_id(token):
    """The pk a token vouches for, or None if it is forged or stale."""
    try:
        return int(_signer.unsign(token, max_age=FILE_LINK_MAX_AGE))
    except (BadSignature, SignatureExpired, ValueError):
        return None

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
        # Deliberately open at the door, closed immediately inside: either a
    # signature naming this exact file, or a logged-in user at its branch.
    permission_classes = [AllowAny]

    def get(self, request, pk):
        job_file = (
            JobFile.objects
            .select_related('job__branch')
            .filter(pk=pk)
            .first()
        )
        if not job_file:
            raise Http404

        token = request.query_params.get('t')
        if token:
            # The signature must name this file. A valid token for one
            # file is worth nothing against another.
            if unsigned_file_id(token) != job_file.pk:
                logger.warning('Bad or expired file token for %s', job_file.pk)
                raise Http404
        elif request.user.is_authenticated:
            branch = getattr(request.user, 'branch', None)
            # Finance and HQ roles carry no branch and legitimately see
            # everything; everyone else is held to their own.
            if branch and job_file.job.branch_id != branch.id:
                logger.warning(
                    'File %s requested by %s from another branch',
                    job_file.pk, request.user.pk,
                )
                raise Http404
        else:
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