"""
Analytics API views.

Session endpoints called by frontend JS:
  POST /api/v1/analytics/session/start/      — on portal load
  POST /api/v1/analytics/session/heartbeat/  — every 60s
  POST /api/v1/analytics/session/event/      — critical-action tab switch
  POST /api/v1/analytics/session/end/        — on logout/unload
"""

from django.db.models import Count
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status


class SessionStartView(APIView):
    """
    POST /api/v1/analytics/session/start/
    Called by frontend on portal load.

    Body:
      { "portal": "CASHIER", "user_agent": "..." }

    Returns:
      { "session_id": 42 }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.analytics.engines.session_engine import SessionEngine

        portal     = request.data.get('portal', '').upper()
        user_agent = request.data.get('user_agent', '')

        valid_portals = [
            'ATTENDANT', 'CASHIER', 'BRANCH_MANAGER',
            'REGIONAL_MANAGER', 'FINANCE', 'BELT_MANAGER',
        ]
        if portal not in valid_portals:
            return Response(
                {'detail': f'Invalid portal. Choose from: {valid_portals}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ip      = self._get_ip(request)
        session = SessionEngine.start_session(
            user       = request.user,
            portal     = portal,
            ip_address = ip,
            user_agent = user_agent,
        )

        if not session:
            return Response(
                {'detail': 'Could not start session.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({'session_id': session.pk}, status=status.HTTP_201_CREATED)

    def _get_ip(self, request):
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            return x_forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')


class SessionHeartbeatView(APIView):
    """
    POST /api/v1/analytics/session/heartbeat/
    Called every 60s by frontend to keep session alive.

    Body:
      { "session_id": 42 }

    Returns:
      { "ok": true, "active_minutes": 12.5 }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.analytics.engines.session_engine import SessionEngine

        session_id = request.data.get('session_id')
        if not session_id:
            return Response({'detail': 'session_id required.'}, status=400)

        session = SessionEngine.heartbeat(session_id, request.user)
        if not session:
            return Response({'detail': 'Session not found.'}, status=404)

        return Response({
            'ok'            : True,
            'active_minutes': session.active_minutes,
        })


class SessionEventView(APIView):
    """
    POST /api/v1/analytics/session/event/
    Called by frontend for high-signal events only:
    - Tab switch while payment modal is open
    - Tab switch while EOD sign-off wizard is open

    Body:
      {
        "session_id": 42,
        "event": "TAB_SWITCH_CRITICAL",
        "context": "payment_modal"
      }

    Returns:
      { "ok": true }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.analytics.engines.session_engine import SessionEngine

        session_id = request.data.get('session_id')
        event      = request.data.get('event', '')
        context    = request.data.get('context', '')

        if not session_id:
            return Response({'detail': 'session_id required.'}, status=400)

        if event == 'TAB_SWITCH_CRITICAL':
            SessionEngine.record_critical_switch(
                session_id     = session_id,
                user           = request.user,
                action_context = context,
            )

        return Response({'ok': True})


class EODPredictionView(APIView):
    """
    GET /api/v1/analytics/prediction/
    Returns EOD job count and revenue prediction interval for today's sheet.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.finance.models import DailySalesSheet
        from apps.finance.services.sheet_summary_service import SheetSummaryService
        from apps.analytics.engines.prediction_engine import PredictionEngine
        from django.utils import timezone
        from django.db.models import Sum

        branch = getattr(request.user, 'branch', None)
        if not branch:
            return Response(
                {'detail': 'No branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        today = timezone.localdate()
        try:
            sheet = DailySalesSheet.objects.get(
                branch = branch,
                date   = today,
            )
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'No sheet found for today.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Current actuals
        from apps.jobs.models import Job
        agg = Job.objects.filter(
            daily_sheet = sheet,
            status      = 'COMPLETE',
        ).aggregate(
            job_count = Count('id'),
            revenue   = Sum('amount_paid'),
        )
        current_jobs    = agg['job_count'] or 0
        current_revenue = float(agg['revenue'] or 0)

        engine = PredictionEngine(branch)
        result = engine.predict(
            sheet           = sheet,
            current_jobs    = current_jobs,
            current_revenue = current_revenue,
        )

        return Response({
            **result,
            'current_jobs'   : current_jobs,
            'current_revenue': current_revenue,
            'sheet_id'       : sheet.pk,
            'sheet_date'     : str(sheet.date),
        })


class SessionEndView(APIView):
    """
    POST /api/v1/analytics/session/end/
    Called on logout or beforeunload event.

    Body:
      { "session_id": 42 }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.analytics.engines.session_engine import SessionEngine

        SessionEngine.close_session(request.user, reason='EXPLICIT_END')
        return Response({'ok': True})