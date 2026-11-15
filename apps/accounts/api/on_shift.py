"""
GET /api/v1/accounts/on-shift/ (15 Nov 2026)

Who is on shift at the manager's branch today, for the sidebar. Branch
Managers only for now: who else should see it is still to be decided.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.on_shift import on_shift

SEES_ON_SHIFT = {'BRANCH_MANAGER'}


class OnShiftView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role = user.role.name if user.role_id else ''
        if role not in SEES_ON_SHIFT or not user.branch_id:
            return Response({'detail': 'Only a Branch Manager can see who is on shift.'}, status=403)
        return Response(on_shift(user.branch, viewer=user))
