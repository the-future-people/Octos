"""
Attendant sign-off endpoints (13 Nov 2026). All logic is in
AttendantSignOffEngine; these views only check who is asking and translate.

  GET  attendant/signoff/status/          the attendant's phase and times
  GET  attendant/signoff/preview/         her day in buckets, the questions, the shelf
  POST attendant/signoff/                 submit answers and sign off
  GET  sheets/<pk>/attendant-signoffs/    the manager's view of every attendant
  POST attendant-signoff-items/<pk>/resolve/   the manager resolves a flagged answer
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsNotShadowUser
from apps.finance.attendant_signoff_engine import (
    AttendantSignOffEngine, SignOffRefused,
)
from apps.finance.models import DailySalesSheet


def _branch_or_400(user):
    branch = getattr(user, 'branch', None)
    if branch is None:
        return None, Response({'detail': 'No branch assigned.'}, status=status.HTTP_400_BAD_REQUEST)
    return branch, None


class AttendantSignOffStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        branch, error = _branch_or_400(request.user)
        if error:
            return error
        return Response(AttendantSignOffEngine(branch).status(request.user))


class AttendantSignOffPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        branch, error = _branch_or_400(request.user)
        if error:
            return error
        engine = AttendantSignOffEngine(branch)
        sheet = engine.today_sheet()
        if sheet is None:
            return Response({'detail': 'There is no day sheet today.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(engine.preview(request.user, sheet))


class AttendantSignOffSubmitView(APIView):
    permission_classes = [IsAuthenticated, IsNotShadowUser]

    def post(self, request):
        branch, error = _branch_or_400(request.user)
        if error:
            return error
        data = request.data or {}
        unpaid = data.get('unpaid') or {}
        shelf = data.get('shelf') or {}
        if not isinstance(unpaid, dict) or not isinstance(shelf, dict):
            return Response(
                {'detail': 'Answers must be sent as {job_id: answer}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        engine = AttendantSignOffEngine(branch)
        try:
            record = engine.submit(
                request.user,
                unpaid_answers=unpaid,
                shelf_answers=shelf,
                handover_note=str(data.get('handover_note') or ''),
            )
        except SignOffRefused as err:
            return Response({'detail': str(err)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                'detail': 'Signed off.',
                'signoff_id': record.pk,
                'signed_off_at': record.signed_off_at.isoformat(),
                'buckets': record.buckets,
            },
            status=status.HTTP_201_CREATED,
        )


class SheetAttendantSignOffsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.select_related('branch').get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response({'detail': 'Sheet not found.'}, status=status.HTTP_404_NOT_FOUND)
        if sheet.branch_id != getattr(request.user, 'branch_id', None):
            return Response({'detail': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(AttendantSignOffEngine(sheet.branch).sheet_overview(sheet))


class AttendantSignOffItemResolveView(APIView):
    permission_classes = [IsAuthenticated, IsNotShadowUser]

    def post(self, request, pk):
        try:
            item = AttendantSignOffEngine.resolve_item(
                pk, request.user, note=str((request.data or {}).get('note') or ''),
            )
        except SignOffRefused as err:
            return Response({'detail': str(err)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'id': item.pk,
            'resolved_at': item.resolved_at.isoformat(),
            'resolution_note': item.resolution_note,
        })
