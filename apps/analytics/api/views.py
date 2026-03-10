from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import get_branch_summary, get_branch_trend


class BranchSummaryView(APIView):
    """
    GET /api/v1/analytics/branch/summary/
    Returns live metrics for the authenticated user's branch.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user   = request.user
        branch = getattr(user, 'branch', None)

        if branch is None:
            return Response({
                'detail': 'No branch assigned to this user.'
            }, status=400)

        # If branch is a bare ID (not expanded), fetch it
        if isinstance(branch, int):
            try:
                from apps.organization.models import Branch
                branch = Branch.objects.get(pk=branch)
            except Exception:
                return Response({'detail': 'Branch not found.'}, status=404)

        summary = get_branch_summary(branch)
        return Response(summary)


class BranchSnapshotTrendView(APIView):
    """
    GET /api/v1/analytics/branch/trend/?days=30
    Returns historical daily snapshots for trend charts.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user   = request.user
        branch = getattr(user, 'branch', None)

        if branch is None:
            return Response({'detail': 'No branch assigned.'}, status=400)

        if isinstance(branch, int):
            try:
                from apps.organization.models import Branch
                branch = Branch.objects.get(pk=branch)
            except Exception:
                return Response({'detail': 'Branch not found.'}, status=404)

        try:
            days = int(request.query_params.get('days', 30))
            days = max(7, min(days, 365))  # clamp between 7 and 365
        except ValueError:
            days = 30

        trend = get_branch_trend(branch, days=days)
        return Response({'days': days, 'data': trend})