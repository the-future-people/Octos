"""
GET /api/v1/jobs/attendant/today/ (16 Nov 2026)

Everything on the attendant's Today screen in one call: see
selectors/attendant_today.py.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.selectors.attendant_today import attendant_today


class AttendantTodayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not getattr(request.user, 'branch_id', None):
            return Response({'detail': 'No branch assigned.'}, status=400)
        return Response(attendant_today(request.user))
