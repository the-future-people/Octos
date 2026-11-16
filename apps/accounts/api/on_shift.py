"""
GET /api/v1/accounts/on-shift/ (15 Nov 2026)

Who is on shift at the branch today, for the sidebar: the Branch Manager's
first, then (16 Nov 2026) every staff portal, so the front desk sees who is on
the till and at the machines.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.on_shift import on_shift


class OnShiftView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user.branch_id:
            return Response({'detail': 'Only staff at a branch can see who is on shift.'}, status=403)
        return Response(on_shift(user.branch, viewer=user))
