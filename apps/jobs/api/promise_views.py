"""
When a job taken at the counter would be ready.

POST /api/v1/jobs/promise/  { lines: [{ service, quantity, pages }] }

The same prediction service that promises online customers, asked about
the whole cart at the attendant's own branch: the floor's real queues,
the work itself, opening hours walked. So the counter and the website
can never promise differently for the same job.

This is an estimate while quoting. The promise itself is fixed when the
deposit is paid, because that is when the job truly joins the line.
"""

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class PromiseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.jobs.models import Service
        from apps.production.services.prediction_service import PredictionService

        # The attendant's own branch, never one the browser names.
        branch = getattr(request.user, 'branch', None)
        if branch is None:
            return Response({'detail': 'Your account has no branch.'}, status=status.HTTP_400_BAD_REQUEST)

        raw = request.data.get('lines') or []
        if not isinstance(raw, list) or not raw:
            return Response({'detail': 'Add something to the job first.'}, status=status.HTTP_400_BAD_REQUEST)

        services = {s.pk: s for s in Service.objects.filter(pk__in=[l.get('service') for l in raw if isinstance(l, dict)])}
        lines = []
        for line in raw:
            if not isinstance(line, dict):
                continue
            service = services.get(line.get('service'))
            if service is None:
                continue
            try:
                quantity = max(1, int(line.get('quantity') or 1))
                pages = max(1, int(line.get('pages') or 1))
            except (TypeError, ValueError):
                continue
            lines.append((service, quantity, pages))
        if not lines:
            return Response({'detail': 'None of those services can be found.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ready_at = PredictionService(branch).predict(lines).ready_at
        except Exception:
            logger.exception('Could not work out a counter promise at %s', branch)
            ready_at = None

        if ready_at is None:
            return Response({'ready_at': None, 'detail': 'Octos cannot say yet: check with the coordinator.'})
        return Response({'ready_at': ready_at.isoformat()})