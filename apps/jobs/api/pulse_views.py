"""
GET /api/v1/jobs/pulse/ (15 Nov 2026)

The branch's pulse for the strip across the top of the BM portal: floor
load, machines up, promises kept. See selectors/branch_pulse.py.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.selectors.branch_pulse import branch_pulse


class BranchPulseView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response({'detail': 'No branch assigned.'}, status=400)
        return Response(branch_pulse(branch))
