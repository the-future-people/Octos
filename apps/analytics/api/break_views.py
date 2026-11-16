"""
POST /api/v1/analytics/session/break/   {on: true | false}   (16 Nov 2026)

"Taking a break" and "I'm back" from the are-you-there check. See
analytics/breaks.py.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.breaks import set_break


class SessionBreakView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        on = bool(request.data.get('on'))
        session = set_break(request.user, on)
        if session is None:
            return Response({'detail': 'No open session.'}, status=404)
        return Response({'on_break': session.on_break_since is not None,
                         'since': session.on_break_since.isoformat() if session.on_break_since else None})
